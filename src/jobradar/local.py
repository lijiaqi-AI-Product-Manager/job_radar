"""用户本地数据的位置、下载地址、打开方式与结果包装。CLI 与 MCP 共用。"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from jobradar.core import queries as q
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts, parse_ts

REPO = "lijiaqi-AI-Product-Manager/job_radar"
GITEE_REPO = os.environ.get("JOBRADAR_GITEE_REPO", "qgauss/job_radar")  # 国内镜像（Gitee 发行版）
RELEASE_TAG = "data-latest"
DB_FILES = {"jobs": "jobs.db", "text": "jd_text.db", "calendar": "calendar.db"}
STALE_HOURS = 48


class NoData(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("JOBRADAR_HOME", Path.home() / ".cache" / "jobradar"))


def github_url(name: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{name}"


def gitee_url(name: str) -> str:
    return f"https://gitee.com/{GITEE_REPO}/releases/download/{RELEASE_TAG}/{name}"


def asset_urls(name: str, prefer: str | None = None) -> list[tuple[str, str]]:
    """按尝试顺序返回 (镜像名, 下载地址)。
    prefer：github / gitee；JOBRADAR_MIRROR 若是 URL 前缀（如 GitHub 加速代理），排在最前。"""
    mirrors = [("github", github_url(name)), ("gitee", gitee_url(name))]
    env = os.environ.get("JOBRADAR_MIRROR", "").strip()
    prefer = prefer or (env if env in ("github", "gitee") else None)
    if prefer == "gitee":
        mirrors.reverse()
    if env.startswith("http"):
        mirrors.insert(0, ("mirror", f"{env.rstrip('/')}/{github_url(name)}"))
    return mirrors


def open_db(kind: str, required: bool = True):
    path = home() / DB_FILES[kind]
    if not path.exists():
        if required:
            raise NoData(f"本地没有数据：{path}。先运行 `jobradar update`。")
        return None
    try:
        return connect(path, kind)
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
    return {"data_as_of": as_of, "stale": stale, **extra, "results": results}

SYNC_META = ".sync.json"


def _meta_path() -> Path:
    return home() / SYNC_META


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


def remote_digests(timeout: float = 6.0) -> dict[str, str]:
    """GitHub Release 里每个 asset 的 sha256 digest（一次 API 调用）。

    用于增量更新：本地记录的 digest 没变就不下载那 20/35MB。
    匿名 60 次/小时够用；拿不到（限流/离线）就返回空，退化成全量下载。
    """
    import httpx

    url = f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}"
    try:
        headers = {"User-Agent": "jobradar/0.1"}
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as c:
            data = c.get(url).json()
        return {a["name"]: a.get("digest") or "" for a in (data.get("assets") or [])}
    except Exception:  # noqa: BLE001
        return {}
