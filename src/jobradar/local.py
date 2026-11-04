"""用户本地数据的位置、下载地址、打开方式与结果包装。CLI 与 MCP 共用。"""

import base64
import json
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from jobradar import __version__
from jobradar.core import queries as q
from jobradar.file_lock import file_lock
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts, parse_ts

REPO = "lijiaqi-AI-Product-Manager/job_radar"
GITEE_REPO = os.environ.get("JOBRADAR_GITEE_REPO", "qgauss/job_radar")  # 国内镜像（Gitee 发行版）
RELEASE_TAG = "data-latest"
DB_FILES = {"jobs": "jobs.db", "text": "jd_text.db", "calendar": "calendar.db"}
STALE_HOURS = 48
_PIN = ContextVar("jobradar_snapshot", default=None)


class NoData(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("JOBRADAR_HOME", Path.home() / ".cache" / "jobradar"))


def _active_directory():
    pointer = home() / ".active.json"
    if not pointer.exists():
        return home()
    try:
        metadata = json.loads(pointer.read_text(encoding="utf-8"))
        relative = metadata["directory"]
        if metadata.get("version") != 1 or not isinstance(relative, str) or not re.fullmatch(r"snapshots/[a-f0-9]{32}", relative):
            raise ValueError
        directory = home() / relative
        if (directory.is_symlink() or directory.parent.is_symlink() or not directory.is_dir()
                or directory.resolve().parent != home().resolve()/"snapshots"):
            raise ValueError
        return directory
    except (ValueError, KeyError, TypeError, OSError):
        raise NoData("本地快照入口损坏；运行 jobradar update --force 恢复") from None


def data_dir():
    return _PIN.get() or _active_directory()


@contextmanager
def snapshot():
    if _PIN.get() is not None:
        yield
        return
    lease = None
    with file_lock(home() / ".catalog.lock"):
        directory = _active_directory()
        lease = directory / (".reader-" + uuid.uuid4().hex)
        guard = file_lock(lease)
        guard.__enter__()
    token = _PIN.set(directory)
    try:
        yield
    finally:
        _PIN.reset(token)
        if lease is not None:
            guard.__exit__(None, None, None)
            lease.unlink(missing_ok=True)


def _retention(keep):
    if type(keep) is not int or not 1 <= keep <= 10:
        raise ValueError("keep 必须是1到10之间的整数")
    return keep


def _managed_directories():
    parent = home() / "snapshots"
    if not parent.exists() or parent.is_symlink() or parent.resolve().parent != home().resolve():
        return []
    return [p for p in parent.iterdir() if re.fullmatch(r"[a-f0-9]{32}",p.name)
            and p.is_dir() and not p.is_symlink() and p.resolve().parent == parent.resolve()]


def _in_use(directory):
    for lease in directory.glob(".reader-*"):
        try:
            with file_lock(lease,timeout=0):
                pass
        except (ValueError,OSError):
            return True
    return False


def _prune_locked(keep):
    active = _active_directory()
    candidates = sorted(_managed_directories(),key=lambda p:(p.stat().st_mtime,p.name),reverse=True)
    previous = [p for p in candidates if p != active and not (p/".building").exists()]
    retained = {active,*previous[:keep-1]}
    removed = 0
    for old in previous:
        if old in retained or _in_use(old):
            continue
        try:
            # 绝对目标已核实为本项目快照目录的直接子目录，拒绝符号链接及junction。
            if old.resolve().parent != (home()/"snapshots").resolve():
                continue
            shutil.rmtree(old)
            removed += 1
        except OSError:
            pass
    if active != home() and len(retained) >= keep and not _in_use(home()):
        for name in (*DB_FILES.values(),SYNC_META):
            legacy = home()/name
            if (active/name).is_file() and legacy.is_file() and not legacy.is_symlink():
                try:
                    legacy.unlink()
                except OSError:
                    pass
    return removed


def prune_snapshots(*, keep=1):
    _retention(keep)
    with file_lock(home()/".catalog.lock"):
        return _prune_locked(keep)


def storage_usage():
    active = _active_directory()
    directories = _managed_directories()
    def size(directory):
        return sum((directory/name).stat().st_size for name in (*DB_FILES.values(),SYNC_META)
                   if (directory/name).is_file() and not (directory/name).is_symlink())
    active_bytes = size(active)
    total = sum(size(p) for p in directories) + size(home())
    return {"active_bytes":active_bytes,"total_bytes":total,"reclaimable_bytes":max(0,total-active_bytes),
            "snapshot_count":len(directories),"active_files":{name:(active/name).stat().st_size
                for name in DB_FILES.values() if (active/name).is_file()}}


def activate(directory, *, keep=1):
    _retention(keep)
    if (not re.fullmatch(r"[a-f0-9]{32}",directory.name) or directory.is_symlink()
            or directory.resolve().parent != home().resolve()/"snapshots" or not directory.is_dir()):
        raise ValueError("活动快照必须位于本地快照目录内")
    relative = directory.relative_to(home()).as_posix()
    with file_lock(home() / ".catalog.lock"):
        temporary = home() / (".active-" + uuid.uuid4().hex)
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump({"version": 1, "directory": relative}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, home() / ".active.json")
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            (directory/".building").unlink(missing_ok=True)
            _prune_locked(keep)
        except OSError:
            pass  # 已提交后清理失败不回滚，也不删除正在使用的旧代。


def discard_uncommitted(directory):
    """中断可能发生在指针提交后；绝不清理正在启用的一代。"""
    with file_lock(home() / ".catalog.lock"):
        try:
            active = _active_directory()
        except NoData:
            return  # 损坏入口交由恢复流程处理，保留可恢复文件。
        if active != directory:
            shutil.rmtree(directory)


def github_url(name: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{name}"


def gitee_url(name: str) -> str:
    return f"https://gitee.com/{GITEE_REPO}/releases/download/{RELEASE_TAG}/{name}"


def asset_urls(name: str, prefer: str | None = None, *, asset_names=None) -> list[tuple[str, str]]:
    """按尝试顺序返回 (镜像名, 下载地址)。
    prefer：github / gitee；JOBRADAR_MIRROR 若是 URL 前缀（如 GitHub 加速代理），排在最前。"""
    immutable = (asset_names or {}).get(name, name)
    mirrors = [("github", github_url(immutable)), ("gitee", gitee_url(name))]
    env = os.environ.get("JOBRADAR_MIRROR", "").strip()
    prefer = prefer or (env if env in ("github", "gitee") else None)
    if prefer == "gitee":
        mirrors.reverse()
    if env.startswith("http"):
        mirrors.insert(0, ("mirror", f"{env.rstrip('/')}/{github_url(immutable)}"))
    return mirrors


def open_db(kind: str, required: bool = True):
    path = data_dir() / DB_FILES[kind]
    if not path.exists():
        if required:
            raise NoData(f"本地没有数据：{path}。先运行 `jobradar update`。")
        return None
    try:
        return connect(path, kind, defer_search_index=True)
    except sqlite3.DatabaseError as e:
        # 文件在但打不开：多半是下载被截断/磁盘问题。给可执行的一条话，
        # 而不是把 sqlite3 的 traceback 甩给用户（CLI 与 MCP 都走这里）。
        raise NoData(
            f"本地库损坏（{e}）：{path}\n"
            "运行 `jobradar update --force` 重新下载即可；反复损坏请检查磁盘空间与网络。"
        ) from e
    except RuntimeError as e:
        # migrate 的「库比代码新」：升级 jobradar 而不是重下数据
        raise NoData(f"{e}（当前库：{path}）") from e


@contextmanager
def db(kind: str, required: bool = True):
    """打开本地库，退出时关闭。

    Windows 上未关闭的连接会一直锁着文件：`jobradar update` 的最后一步是
    `tmp.replace(dest)`，库文件被锁时会报 PermissionError: [WinError 32]。
    MCP server 常驻进程，不关闭还会每调用一次泄漏一个句柄。
    """
    conn = open_db(kind, required)
    if conn is None:
        yield None
        return
    try:
        yield conn
    finally:
        conn.close()


def envelope(conn, results, *, as_of: str | None = None, **extra) -> dict:
    """统一的返回包装。conn 为 jobs.db；日历等其他库传 conn=None 并显式给出 as_of。"""
    as_of = as_of if conn is None else q.data_as_of(conn)
    stale = as_of is None or (parse_ts(now_ts()) - parse_ts(as_of)).total_seconds() > STALE_HOURS * 3600
    rows = results if isinstance(results, list) else [r for group in results.values() if isinstance(group, list) for r in group] if isinstance(results, dict) else []
    if any(isinstance(row, dict) and row.get("source_stale") for row in rows):
        stale = True
    return {"data_as_of": as_of, "stale": stale, **extra, "results": results}

SYNC_META = ".sync.json"


def _meta_path() -> Path:
    return data_dir() / SYNC_META


def load_sync_meta() -> dict:
    import json

    p = _meta_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001 — 元数据坏了就当没有
        return {}


def save_sync_meta(meta: dict) -> None:
    import json

    try:
        _meta_path().write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


class RemoteDigests(dict):
    def __init__(self, values, *, asset_names=None, generation=None, compact_text=None):
        super().__init__(values)
        self.asset_names = asset_names or {}
        self.generation = generation
        self.compact_text = compact_text


def select_text_storage(remote, *, compact=True):
    variant = getattr(remote, "compact_text", None)
    if not compact or not variant:
        return remote
    return RemoteDigests({**remote, "jd_text.db.gz":"sha256:"+variant["sha256"]},
        asset_names={**remote.asset_names,"jd_text.db.gz":variant["asset"]},
        generation=remote.generation, compact_text=variant)


def snapshot_digests(data):
    if not isinstance(data, dict):
        raise ValueError("远端发布元数据格式错误")
    body = data.get("body") or ""
    marker = re.search(r"<!--jobradar-snapshot:(.*?)-->", body, re.S)
    if marker is None:
        return RemoteDigests({a["name"]: a.get("digest") or "" for a in data.get("assets", [])})
    try:
        manifest = json.loads(base64.b64decode(marker[1], validate=True))
        files = manifest["files"]
        required = {"jobs.db.gz", "jd_text.db.gz", "calendar.db.gz"}
        if manifest["version"] != 1 or set(files) != required or not re.fullmatch(r"[a-f0-9]{20}", manifest["generation"]):
            raise ValueError
        names, digests = {}, {}
        for name, info in files.items():
            if not re.fullmatch(r"[a-f0-9]{64}", info["sha256"]):
                raise ValueError
            if info["asset"] != info["sha256"][:20] + "-" + name or type(info["size"]) is not int or info["size"] <= 0:
                raise ValueError
            names[name] = info["asset"]
            digests[name] = "sha256:" + info["sha256"]
        variants = manifest.get("variants", {})
        if not isinstance(variants,dict):
            raise ValueError
        variant = variants.get("text_compact")
        if variant is not None:
            if (not isinstance(variant,dict) or variant.get("version") != 1
                    or not re.fullmatch(r"[a-f0-9]{64}",str(variant.get("sha256", "")))
                    or variant.get("asset") != variant["sha256"][:20]+"-jd_text.compact.db.gz"
                    or variant.get("source_sha256") != files["jd_text.db.gz"]["sha256"]
                    or type(variant.get("size")) is not int or variant["size"] <= 0):
                raise ValueError
        return RemoteDigests(digests, asset_names=names, generation=manifest["generation"],compact_text=variant)
    except (ValueError, KeyError, TypeError):
        raise ValueError("已提交的快照清单无效，保留本地数据") from None


def remote_digests(timeout: float = 6.0) -> dict[str, str]:
    """GitHub Release 里每个 asset 的 sha256 digest（一次 API 调用）。

    用于增量更新：本地记录的 digest 没变就不下载那 20/35MB。
    元数据请求失败时使用独立匿名镜像会话；两者均失败则拒绝覆盖本地数据。
    """
    import httpx

    url = f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}"
    token = os.environ.get("JOBRADAR_GITHUB_TOKEN", "").strip()
    requests = [{}] + ([{"Authorization": f"Bearer {token}"}] if token else [])
    for auth in requests:
        try:
            with httpx.Client(headers={"User-Agent": f"jobradar/{__version__}"},
                              timeout=timeout, follow_redirects=True) as c:
                response = c.get(url, headers=auth)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError):
            continue
        else:
            # 已提交但无效的清单仍拒绝；不能以镜像掩盖损坏的主发布清单。
            return snapshot_digests(data)
    else:
        try:
            with httpx.Client(headers={"User-Agent": f"jobradar/{__version__}"},
                              timeout=timeout, follow_redirects=True) as mirror:
                response = mirror.get(gitee_url("snapshot-manifest.json"))
                response.raise_for_status()
                manifest = response.json()
            files = manifest["files"]
            required = {"jobs.db.gz", "jd_text.db.gz", "calendar.db.gz"}
            if manifest["version"] != 1 or not required <= set(files):
                return {}
            values = {name: "sha256:" + files[name]["sha256"] for name in required}
            if any(not re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in values.values()):
                return {}
            return RemoteDigests(values, generation=manifest["generation"])
        except Exception:  # noqa: BLE001
            return {}
