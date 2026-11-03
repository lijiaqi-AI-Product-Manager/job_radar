"""jobradar 命令行。所有查询都调用 core/queries.py；输出默认 JSON（给 agent），--table 输出表格（给人）。

每个查询结果都带 data_as_of（数据截至时间），skill 要求 agent 在回答里引用它。
"""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path

import httpx

from jobradar.core import queries as q
from jobradar.file_lock import file_lock
from jobradar.local import (
    DB_FILES,
    RELEASE_TAG,
    REPO,
    NoData,
    activate,
    asset_urls,
    data_dir,
    db,
    discard_uncommitted,
    envelope,
    home,
    snapshot,
)
from jobradar.store.migrate import connect, migration_files
from jobradar.timeutil import now_ts


@contextmanager
def _open(kind: str, required: bool = True):
    try:
        with db(kind, required) as conn:
            yield conn
    except NoData as e:
        raise SystemExit(str(e)) from e


def _emit(args, payload: dict):
    if getattr(args, "table", False) and isinstance(payload.get("results"), list):
        rows = payload["results"]
        count = f"返回 {len(rows)}/{payload['total']} 条" if "total" in payload else f"{len(rows)} 条"
        print(f"# data_as_of: {payload.get('data_as_of')}  ({count})")
        if payload.get("stale"):
            print("# 数据陈旧：部分来源超过 48 小时未核实，岗位是否仍在招需查看来源。可先运行 jobradar update。")
        if any(r.get("source_enabled") is False for r in rows):
            print("# 部分记录的来源已停用：这些记录属于历史观测，当前可投状态需另行核实；停用不等于岗位已关闭。")
        if payload.get("truncated"):
            print("# 结果已截断：请缩小筛选范围，或调整返回条数。")
        if payload.get("count_unit") == "folded_groups":
            print("# 已折叠相同展示分组；variants为原记录数，--no-dedupe可查看全部记录。")
        if any(r.get("field_warnings") for r in rows):
            print("# 部分岗位有资格字段冲突或跨届次渠道；请查看详情中的field_warnings和qualification_evidence。")
        if any(r.get("url_scope") == "project_listing" for r in rows):
            print("# 部分链接为项目职位列表，需按标题查找；并非直达岗位详情或申请链接。")
        if rows and "project_type" in rows[0]:  # 日历：一条一块，别把 20 个字段堆一行
            for r in rows:
                _print_calendar_row(r)
        elif rows and "title" in rows[0]:  # 岗位 / 事件
            print("截止日 | 公司 | 岗位 | 城市 | 类型 | 届次 | URL")
            for r in rows:
                cities = "/".join(r.get("cities") or [])
                # 截止日：用户最先想知道的就是「还能不能投」。没有截止日写「未知」而不是空，
                # 也不能写成「已截止」——源没说就是没说。
                print(" | ".join(str(x) for x in (
                    r.get("apply_end") or "未知", r.get("company"), r.get("title"), cities or "-",
                    r.get("type") or r.get("recruit_type"),
                    r.get("grad_year") or "-", r.get("url"))))
        elif rows:  # 其他（数据源状态、趋势）：按字段输出
            cols = list(rows[0].keys())
            print(" | ".join(cols))
            for r in rows:
                print(" | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols))
        if payload.get("hint"):
            print(f"\n{payload['hint']}")
        for hint in payload.get("hints") or []:
            print(f"# {hint}")
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _fmt_window(r: dict) -> str:
    start, end = r.get("apply_start"), r.get("apply_end")
    if start and end:
        return f"{start} ~ {end}"
    if start:
        return f"{start} 起（未写截止）"
    if end:
        return f"截止 {end}"
    return "来源未写（不代表已截止）"


def _print_calendar_row(r: dict):
    """人读的日历条目：按 docs/CALENDAR-FORMAT.md 的字段顺序，缺的写「未提供」。"""
    head = " · ".join(x for x in (r.get("group_name"), f"{r['grad_year']}届" if r.get("grad_year") else None,
                                  r.get("project_type")) if x)
    print(f"\n{head}")
    if r.get("company") and r["company"] != r.get("group_name"):
        print(f"  公司/产品：{r['company']}")
    tracks = r.get("tracks") or []
    if tracks:
        parts = []
        for t in tracks:
            roles = "、".join((t or {}).get("roles") or [])
            parts.append(f"{t.get('direction')}（{roles}）" if roles else str(t.get("direction")))
        print(f"  方向：{'；'.join(parts)}")
    print(f"  网申：{_fmt_window(r)}")
    if r.get("deadline_scope") == "job_evidence":
        print("  注意：日期来自岗位样本，不代表整个批次同一天截止")
    print(f"  城市：{'、'.join(r.get('cities') or []) or '未提供'}")
    print(f"  入口：{r.get('apply_url') or '未提供'}")
    if r.get("apply_url_scope") == "project_listing":
        print("  入口说明：项目职位列表，需按岗位标题查找，并非直达申请页")
    src = r.get("source") or {}
    when = f"（{src['date']}）" if src.get("date") else ""
    print(f"  来源：{src.get('name')}{when}")
    status = r.get("jd_status")
    extra = {"linked": "可在 search 里查到 JD", "official_page": "有官方 JD 页",
             "blocked": "JD 被挡，只发日历", "none": "无公开 JD"}.get(status, status)
    print(f"  JD：{extra}")
    if r.get("window_status") == "unknown":
        print("  注意：来源没写网申起止，不能断定今天还能投")


def _github_api_asset(name: str, client: httpx.Client, token: str) -> tuple[str, dict] | None:
    """仓库未公开时：通过 GitHub API 带鉴权下载 Release 资源。"""
    auth = {"Authorization": f"Bearer {token}"}
    r = client.get(f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}", headers=auth)
    r.raise_for_status()
    asset = next((a for a in r.json().get("assets", []) if a["name"] == name), None)
    return (asset["url"], {**auth, "Accept": "application/octet-stream"}) if asset else None


SLOW_AFTER_SECONDS = 30      # 开始评估吞吐
SLOW_MIN_RATE = 25 * 1024    # 低于 25KB/s 视为不可用
SLOW_MAX_PROJECTED = 300     # 按当前速率预计还要超过 5 分钟，就别等了
MAX_DOWNLOAD_SECONDS = 480   # 单个文件的硬上限
MAX_MIRROR_SECONDS = 120     # 给另一个镜像保留切换机会


def _now() -> float:
    return time.monotonic()


def _local_db_ok(path: Path, name: str | None = None) -> bool:
    """本地库是否能正常打开（增量更新「跳过下载」前必须验一下）。

    背景：digest 一致就跳过下载，但如果本地文件被截断/损坏，用户会一直卡在坏库上。
    `quick_check(1)` 只做轻量校验，85MB 的库通常 <1s。
    """
    if not path.exists():
        return False
    try:
        with path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                return False
        kind = {"jobs.db": "jobs", "jd_text.db": "text", "calendar.db": "calendar"}.get(name or path.name)
        if kind is None:
            return False
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            from jobradar.store.validate import validate_database
            validate_database(con, kind)
            return True
        finally:
            con.close()
    except (sqlite3.DatabaseError, OSError, ValueError):
        return False


def _fetch(client: httpx.Client, url: str, headers: dict, dest_dir: Path, *, deadline=None,
           max_bytes=1024 * 1024 * 1024) -> Path | None:
    """下载到临时文件；404 返回 None。

    先关闭文件再删除：Windows 上删除仍被打开的文件会报 WinError 32。
    慢镜像要尽早放弃：read timeout 只约束"多久没收到字节"，对每秒滴几 KB 的连接无效
    （2026-10-22 实测 Gitee 一次 update 卡了 14 分钟还没完），所以按吞吐与总时长兜底。
    """
    fd, name = tempfile.mkstemp(dir=dest_dir, suffix=".part")
    tmp = Path(name)
    not_found = False
    started, received, slow_checked = _now(), 0, False
    deadline = min(deadline, started + MAX_DOWNLOAD_SECONDS) if deadline is not None else started + MAX_DOWNLOAD_SECONDS
    try:
        from jobradar.http_limits import DeadlineStream, RequestBudgetExceeded

        if _now() >= deadline:
            os.close(fd)
            raise RequestBudgetExceeded("request budget exceeded")
        remaining = max(.001, deadline - _now())
        with os.fdopen(fd, "wb") as out, client.stream("GET", url, headers=headers,
                timeout=httpx.Timeout(min(20, remaining), connect=min(8, remaining))) as resp:
            resp.stream = DeadlineStream(resp.stream, deadline, clock=_now)
            if resp.status_code == 404:
                not_found = True
            else:
                resp.raise_for_status()
                size = int(resp.headers.get("content-length") or 0)
                if size > max_bytes:
                    raise ValueError("下载大小超过上限")
                for chunk in resp.iter_bytes():
                    received += len(chunk)
                    if received > max_bytes:
                        raise ValueError("下载大小超过上限")
                    out.write(chunk)
                    elapsed = _now() - started
                    if elapsed > MAX_DOWNLOAD_SECONDS:
                        raise httpx.ReadTimeout(f"下载超时（{elapsed:.0f}s，已收 {received} 字节）")
                    if not slow_checked and elapsed >= SLOW_AFTER_SECONDS:
                        slow_checked = True
                        rate = received / elapsed
                        projected = size / rate if size and rate else 0
                        if rate < SLOW_MIN_RATE and (not size or projected > SLOW_MAX_PROJECTED):
                            raise httpx.ReadTimeout(
                                f"下载太慢（{rate / 1024:.0f}KB/s，预计还需 {projected:.0f}s）")
    except RequestBudgetExceeded:
        tmp.unlink(missing_ok=True)
        raise httpx.ReadTimeout("下载超过整份文件时间预算") from None
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if not_found:
        tmp.unlink(missing_ok=True)
        return None
    return tmp


def _install(tmp: Path, name: str, gz: bool, dest: Path, expected_digest=None, *, previous=None):
    """解压（若为 .gz）并校验 SQLite 完整性后替换目标文件。"""
    baseline = Path(previous) if previous is not None else dest
    kind = {value:key for key,value in DB_FILES.items()}.get(name)
    if kind and baseline.is_file():
        try:
            with closing(sqlite3.connect(baseline.resolve().as_uri()+"?mode=ro", uri=True)) as old:
                local_version = old.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.DatabaseError:
            local_version = None
        if local_version is not None and local_version > len(migration_files(kind)):
            if tmp != baseline:
                tmp.unlink(missing_ok=True)
            raise ValueError("本地数据库版本高于客户端，请先升级软件；保留原目录并可改用新的 JOBRADAR_HOME")
    if expected_digest:
        with tmp.open("rb") as handle:
            actual = "sha256:" + hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected_digest:
            tmp.unlink(missing_ok=True)
            raise ValueError("下载字节与发布摘要不一致")
    if gz:
        raw = tmp.with_suffix(".raw")
        try:
            with gzip.open(tmp) as src, open(raw, "wb") as out:
                shutil.copyfileobj(src, out)
        except (OSError, EOFError):
            raw.unlink(missing_ok=True)
            tmp.unlink()
            raise ValueError("压缩包损坏") from None
        tmp.unlink()
        tmp = raw
    ok = _local_db_ok(tmp, name)
    invalid_reason = "不是有效的数据库"
    if ok and _local_db_ok(baseline, name):
        table = {"jobs.db": "job", "jd_text.db": "job_text", "calendar.db": "entry"}[name]
        with closing(sqlite3.connect(tmp.resolve().as_uri()+"?mode=rw", uri=True)) as new, closing(sqlite3.connect(baseline.resolve().as_uri()+"?mode=ro", uri=True)) as old:
            new_count = new.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            old_count = old.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            ok = not (old_count and (new_count == 0 or (name == "jobs.db" and new_count < old_count)))
            stamp = {"jobs.db": "SELECT MAX(ts) FROM source_run WHERE status='ok'",
                     "jd_text.db": "SELECT MAX(fetched_at) FROM job_text",
                     "calendar.db": "SELECT MAX(ts) FROM build"}[name]
            old_ts, new_ts = old.execute(stamp).fetchone()[0], new.execute(stamp).fetchone()[0]
            if old_ts and (not new_ts or new_ts < old_ts):
                ok = False
            if ok and name == "jobs.db":
                new.execute("ATTACH DATABASE ? AS previous_snapshot", (baseline.resolve().as_uri()+"?mode=ro",))
                lost_history = new.execute(
                    "SELECT 1 FROM previous_snapshot.job old LEFT JOIN main.job current ON current.id=old.id "
                    "WHERE current.id IS NULL OR current.first_seen IS NOT old.first_seen LIMIT 1").fetchone()
                if lost_history:
                    ok = False
                    invalid_reason = "快照缺少已有岗位或改写首次观测时间，保留历史数据"
    if not ok:
        tmp.unlink()
        raise ValueError(invalid_reason)
    tmp.replace(dest)


def _fetch_parts(client: httpx.Client, name: str, mirror: str, dest_dir: Path, *, deadline=None) -> Path | None:
    """按 `<name>.part01/.part02…` 顺序下载并拼成一个临时文件；一个分片都没有则返回 None。

    Gitee 上行慢，大文件在镜像侧是分片存放的（见 scripts/publish_gitee.py）。
    拼接后的文件仍会过 gzip + SQLite quick_check，损坏会抛 ValueError。
    """
    tmp_all = None
    count = 0
    deadline = deadline if deadline is not None else _now() + MAX_DOWNLOAD_SECONDS
    try:
        for idx in range(1, 100):
            part = f"{name}.part{idx:02d}"
            url = dict(asset_urls(part)).get(mirror)
            if not url:
                break
            piece = _fetch(client, url, {}, dest_dir, deadline=deadline)
            if piece is None:
                break
            if tmp_all is None:
                tmp_all = dest_dir / f".{name}.joined.part"
                tmp_all.unlink(missing_ok=True)
            with open(tmp_all, "ab") as out, open(piece, "rb") as src:
                shutil.copyfileobj(src, out)
            piece.unlink(missing_ok=True)
            count += 1
    except BaseException:
        if tmp_all is not None:
            tmp_all.unlink(missing_ok=True)
        raise
    if count == 0:
        return None
    print(f"{mirror}: {name} 由 {count} 个分片拼接", file=sys.stderr)
    return tmp_all


def _download(name: str, dest: Path, client: httpx.Client | None = None, prefer: str | None = None,
              digests=None, verified=None, previous=None) -> str:
    """依次尝试各镜像，每个镜像先取压缩版 <name>.gz，没有再取原文件。返回实际使用的镜像名。"""
    if client is None:
        with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=True) as owned:
            return _download(name, dest, client=owned, prefer=prefer, digests=digests, verified=verified, previous=previous)
    dest.parent.mkdir(parents=True, exist_ok=True)
    names = getattr(digests, "asset_names", {})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:  # 私有仓库：只能走 GitHub API
        asset = name + ".gz" if name + ".gz" in names else name
        found = _github_api_asset(names.get(asset, asset), client, token)
        if found is None:
            raise SystemExit(f"Release {RELEASE_TAG} 中没有 {name}")
        tmp = _fetch(client, found[0], found[1], dest.parent)
        if tmp is None:
            raise SystemExit(f"下载 {name} 失败（404）")
        try:
            expected = (digests or {}).get(asset)
            if digests and not expected:
                tmp.unlink(missing_ok=True)
                raise ValueError("发布摘要缺失，无法核验下载内容")
            _install(tmp, name, asset.endswith(".gz"), dest, expected, previous=previous)
            if expected and verified is not None:
                verified.pop(name, None)
                verified.pop(name + ".gz", None)
                verified[asset] = expected
        except ValueError as e:
            raise SystemExit(f"下载的 {name} {e}") from None
        return "github"
    errors, invalid = [], False
    overall_deadline = _now() + MAX_DOWNLOAD_SECONDS
    for (mirror, url), (_, gz_url) in zip(asset_urls(name, prefer, asset_names=names), asset_urls(name + ".gz", prefer, asset_names=names), strict=True):
        deadline = min(overall_deadline, _now() + MAX_MIRROR_SECONDS)
        for candidate, gz in ((gz_url, True), (url, False)):
            try:
                if mirror == "gitee" and gz and digests:
                    from jobradar.mirror_download import fetch_snapshot

                    tmp = fetch_snapshot(client, name + ".gz", dest.parent,
                                         expected=digests.get(name + ".gz"), fetch=_fetch,
                                         deadline=deadline, clock=_now)
                else:
                    tmp = _fetch(client, candidate, {}, dest.parent, deadline=deadline)
                if tmp is None and gz:
                    # 大文件在镜像侧是分片存放的：整文件 404 时按 .partNN 拼接
                    tmp = _fetch_parts(client, name + ".gz", mirror, dest.parent, deadline=deadline)
                if tmp is None:
                    continue
                asset = name + ".gz" if gz else name
                expected = (digests or {}).get(asset)
                if digests and not expected:
                    tmp.unlink(missing_ok=True)
                    raise ValueError("发布摘要缺失，无法核验下载内容")
                _install(tmp, name, gz, dest, expected, previous=previous)
                if expected and verified is not None:
                    verified.pop(name, None)
                    verified.pop(name + ".gz", None)
                    verified[asset] = expected
                return mirror
            except httpx.HTTPError as e:
                errors.append(f"{mirror}: {type(e).__name__}")
                break  # 该镜像不可达，换下一个
            except ValueError as e:
                errors.append(f"{mirror}: {e}")
                invalid = True
                if mirror == "gitee" and digests:
                    break
    if invalid:
        raise SystemExit(f"下载的 {name} 不是有效的数据库（{'; '.join(errors)}）")
    raise SystemExit(f"下载 {name} 失败（{'; '.join(errors) or '404'}）。"
                     "请检查GitHub网络连接后重试 `jobradar update`。镜像状态见 "
                     "https://github.com/lijiaqi-AI-Product-Manager/job_radar/blob/main/docs/DISTRIBUTION.md；"
                     "仅访问私有发行版时需要设置 GITHUB_TOKEN。")


def _text_coverage(home_dir: Path) -> float | None:
    """全部未下架岗位的正文行覆盖率，仅诊断缺失，不作快照一致性证据。"""
    jobs_db, text_db = home_dir / DB_FILES["jobs"], home_dir / DB_FILES["text"]
    if not jobs_db.exists() or not text_db.exists():
        return None
    j = sqlite3.connect(jobs_db)
    t = sqlite3.connect(text_db)
    try:
        return q.jd_row_coverage(j, t)
    finally:
        j.close()
        t.close()


def cmd_update(args):
    with file_lock(home() / ".update.lock", timeout=0):
        _update_snapshot(args)


def _missing_indexes(directory, kinds):
    tables = {"jobs":"job_fts", "text":"job_text_fts"}
    missing = []
    for kind in kinds:
        if kind not in tables or not (directory / DB_FILES[kind]).is_file():
            continue
        with closing(sqlite3.connect((directory / DB_FILES[kind]).resolve().as_uri()+"?mode=ro", uri=True)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tables[kind],)).fetchone():
                missing.append(kind)
    return missing


def _prepare_indexes(directory, kinds):
    prepared = _missing_indexes(directory, kinds)
    for kind in prepared:
        print(f"准备 {DB_FILES[kind]} 的全文索引，完成后切换快照…", file=sys.stderr, flush=True)
        with closing(connect(directory / DB_FILES[kind], kind)):
            pass
    return prepared


def _update_snapshot(args):
    home().mkdir(parents=True, exist_ok=True)
    kinds = ["jobs", "calendar"] if args.jobs_only else ["jobs", "text", "calendar"]
    requested = kinds.copy()
    prepare_indexes = getattr(args, "prepare_index", False) and not getattr(args, "no_index", False)
    from jobradar.local import load_sync_meta, remote_digests
    try:
        old = data_dir()
        meta = load_sync_meta()
    except NoData:
        if not args.force:
            raise
        old, meta = home(), {}
    remote = remote_digests()
    if not remote:
        raise SystemExit("无法核实远端完整性清单，保留本地快照；请稍后或切换网络重试")
    verified = {}
    skipped: list[str] = []
    if remote and not getattr(args, "force", False):
        for k in list(kinds):
            assets = (DB_FILES[k] + ".gz", DB_FILES[k])
            trusted = meta.get("_verified_assets", {})
            if (any(remote.get(a) and trusted.get(a) == remote[a] for a in assets)
                    and _local_db_ok(old / DB_FILES[k])):
                kinds.remove(k)
                skipped.append(k)
    if skipped and not kinds and (not prepare_indexes or not _missing_indexes(old, requested)):
        with _open("jobs") as conn:
            print(json.dumps({"updated": [], "skipped": skipped, "data_as_of": q.data_as_of(conn),
                              "home": str(home())}, ensure_ascii=False))
        return
    parent = home() / "snapshots"
    parent.mkdir(exist_ok=True)
    if parent.is_symlink():
        raise SystemExit("快照目录不能是符号链接")
    staging = parent / uuid.uuid4().hex
    staging.mkdir()
    committed = False
    used = {}
    try:
        # backup读取一致SQLite视图，避免复制正处于本地FTS事务中的文件。
        for kind, name in DB_FILES.items():
            if args.jobs_only and kind == "text" and "jobs" in kinds:
                continue
            if kind in kinds:
                continue  # 即将下载的文件直接与旧代核对，无需先复制后覆盖。
            source = old / name
            if _local_db_ok(source, name):
                with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original, \
                        closing(sqlite3.connect(staging / name)) as copied:
                    original.backup(copied)
        with ThreadPoolExecutor(max_workers=max(1, len(kinds))) as pool:
            futures = [(kind, pool.submit(_download, DB_FILES[kind], staging / DB_FILES[kind], prefer=args.mirror, previous=old / DB_FILES[kind],
                        **({"digests": remote, "verified": verified} if remote else {}))) for kind in kinds]
            errors = []
            for kind, future in futures:
                try:
                    used[kind] = future.result()
                except BaseException as exc:
                    errors.append(exc)
            if errors:
                raise errors[0]
        for kind in set(kinds) | set(skipped):
            if not _local_db_ok(staging / DB_FILES[kind]):
                raise SystemExit(f"{DB_FILES[kind]} 业务结构校验失败，保留原快照")
        if not args.jobs_only:
            with closing(sqlite3.connect(staging / DB_FILES["jobs"])) as check:
                check.execute("ATTACH DATABASE ? AS jd", (str(staging / DB_FILES["text"]),))
                if check.execute("SELECT 1 FROM jd.job_text t LEFT JOIN job j ON j.id=t.job_id WHERE j.id IS NULL LIMIT 1").fetchone():
                    raise SystemExit("正文含无法关联岗位，保留原快照")
        prepared = _prepare_indexes(staging, requested) if prepare_indexes else []
        for kind in kinds:
            for asset in (DB_FILES[kind], DB_FILES[kind] + ".gz"):
                meta.pop(asset, None)
                meta.setdefault("_verified_assets", {}).pop(asset, None)
                if asset in verified:
                    meta[asset] = meta["_verified_assets"][asset] = verified[asset]
        if not (staging / DB_FILES["text"]).exists():
            for asset in (DB_FILES["text"], DB_FILES["text"] + ".gz"):
                meta.pop(asset, None)
                meta.setdefault("_verified_assets", {}).pop(asset, None)
        (staging / ".sync.json").write_text(json.dumps(meta), encoding="utf-8")
        activate(staging)
        committed = True
    finally:
        if not committed:
            discard_uncommitted(staging)
    with _open("jobs") as conn:
        out = {"updated": kinds,
               "mirror": {k: used.get(k) for k in kinds},
               "data_as_of": q.data_as_of(conn), "home": str(home()), "data_dir": str(data_dir())}
        out["indexes_prepared"] = prepared
        if skipped:
            out["skipped"] = skipped
        print(json.dumps(out, ensure_ascii=False))


def _company_note(term, info, err=None, quiet=False):
    """把「公司名没对上」说出来。

    查询层对没把握的公司返回 0 行（而不是挑一家最像的）。理由不写出来，用户
    只会看到"空结果"并以为这家公司没在招——所以必须给一句话说明是「未收录/不唯一」。

    quiet=True：日历里能查到这家公司时用（名字是对的，只是没有岗位数据，
    "没有这家公司"这种话会误导）。
    """
    err = err or sys.stderr
    if quiet or not term or not info:
        return
    mode, matched = info.get("match"), info.get("matched") or []
    cands = info.get("candidates") or []
    if mode == "none":
        if cands:
            print(f"注意：数据集中没有名为「{term}」的公司；最接近的是「{'、'.join(cands)}」。"
                  "要按子串搜索请加 --contains。", file=err)
        elif info.get("alias_target"):
            print(f"注意：「{term}」按简称映射到「{info['alias_target']}」，但数据集中还没有这家公司。", file=err)
        else:
            print(f"注意：数据集中没有名为「{term}」的公司（`jobradar stats` 可看收录规模）。", file=err)
    elif mode == "ambiguous":
        print(f"注意：「{term}」命中多家公司（{'、'.join(cands)}），未返回结果；"
              "请写更完整的公司名，或加 --contains 一次性搜全部。", file=err)
    elif mode == "contains" and len(matched) > 1:
        print(f"注意：「{term}」按子串命中 {len(matched)} 家公司（{'、'.join(matched[:5])}）。", file=err)


def cmd_search(args):
    text_cm = _open("text", required=False)
    with _open("jobs") as conn, text_cm as text:
        if args.text and text is None:
            raise SystemExit("全文检索需要 JD 原文库：先运行 `jobradar update`")
        meta = {}
        rows = q.search_jobs(conn, company=args.company, category=args.category, city=args.city,
                             recruit_type=args.type, grad_year=args.grad_year, keyword=args.keyword,
                             text=args.text, text_conn=text, include_closed=args.include_closed,
                             limit=args.limit, contains=args.contains, meta=meta,
                             dedupe=args.dedupe, exclude_store=args.exclude_store,
                             deadline_before=getattr(args, "deadline_before", None),
                             deadline_after=getattr(args, "deadline_after", None),
                             cities=args.cities, exclude_cities=args.exclude_city,
                             exclude_keywords=args.exclude_keyword, exclude_companies=args.exclude_company,
                             include_unknown_grad_year=args.include_unknown_grad_year)
        payload = envelope(conn, rows, **meta)
        hints = list(meta.get("hints", []))
        cal_hint = None
        if not rows and args.company:
            # 「字节/华为/小米」这类只做日历的公司，不能只回一句"数据里没有"
            with _open("calendar", required=False) as cal:
                if cal is not None:
                    cal_hint = q.calendar_hint(cal, args.company)
        _company_note(args.company, meta.get("company_match"), quiet=bool(cal_hint))
        if cal_hint:
            payload["calendar"] = cal_hint
            hints = [h for h in hints if "公司名没有唯一确定" not in h]   # 名字是对的，只是没岗位数据
            hints.append(q.calendar_supplement_hint(meta, cal_hint) + f"：`{cal_hint['cli_hint']}`")
            if cal_hint.get("hint"):
                hints.append(cal_hint["hint"])
        if hints:
            payload["hints"] = hints
        _emit(args, payload)



def cmd_show(args):
    with _open("jobs") as conn, _open("text", required=False) as text:
        job = q.get_job(conn, text, args.job_id)
        _emit(args, envelope(conn, [job] if job else [], found=job is not None))


def cmd_diff(args):
    with _open("jobs") as conn:
        since = q.lookback_since(args.days, now=now_ts())
        meta = {}
        if args.by:
            rows = q.new_jobs_by_category(conn, since=since, limit=args.limit, company=args.company,
                                          contains=args.contains, meta=meta)
            _company_note(args.company, meta.get("company_match"))
            _emit(args, envelope(conn, rows, since=since, by=args.by, **meta))
            return
        rows = q.recent_changes(conn, since=since, company=args.company,
                                types=args.types.split(",") if args.types else None, limit=args.limit,
                                contains=args.contains, meta=meta)
        _company_note(args.company, meta.get("company_match"))
        _emit(args, envelope(conn, rows, since=since, **meta))



def cmd_compare(args):
    with _open("jobs") as conn, _open("text", required=False) as text_conn:
        if text_conn is None:
            raise SystemExit("对比需要 JD 原文库：先运行 `jobradar update`。")
        if not args.category and not args.keyword and not args.text:
            raise SystemExit("compare 需要 --category、--keyword 或 --text")
        meta = {}
        out = q.compare_roles(conn, text_conn, args.companies, args.category, keyword=args.keyword,
                              text=args.text, per_company=args.per_company, meta=meta,
                              city=args.city, recruit_type=args.type, grad_year=args.grad_year)
        _emit(args, envelope(conn, out, category=args.category, keyword=args.keyword, text=args.text,
                              not_found=[c for c, v in out.items() if not v], **meta))


def cmd_trends(args):
    with _open("jobs") as conn:
        meta = {}
        rows = q.company_trend(conn, args.company, until=now_ts(), step_days=args.step_days, meta=meta)
        _company_note(args.company, meta.get("company_match"))
        _emit(args, envelope(conn, rows, company=args.company, **meta))


def cmd_sources(args):
    with _open("jobs") as conn:
        rows = q.data_status(conn, now=now_ts())
        if getattr(args, "problems", False):
            # 排障用：只看「上次没成功」或「过期」的源（rejected 会一直挂着旧岗位，值得盯）
            rows = [r for r in rows if r["stale"] or r.get("last_status") != "ok"]
        if getattr(args, "summary", False):
            failing = [r["source_id"] for r in rows if r["stale"]]
            payload = envelope(conn, [], failing=failing[:20], omitted_failing=max(0, len(failing) - 20),
                               **q.data_status_summary(rows))
        else:
            payload = envelope(conn, rows, failing=[r["source_id"] for r in rows if r["stale"]])
        _emit(args, payload)


def cmd_doctor(args):
    if getattr(args, "robots", False):
        _doctor_robots(args)
        return
    out = {"home": str(home()), "data_dir": str(data_dir()),
           "jobs_db": _local_db_ok(data_dir() / DB_FILES["jobs"]),
           "jd_text_db": _local_db_ok(data_dir() / DB_FILES["text"]),
           "calendar_db": _local_db_ok(data_dir() / DB_FILES["calendar"])}
    if not out["jobs_db"] and (data_dir() / DB_FILES["jobs"]).exists():
        # 文件在但打不开：多半是下载被截断/磁盘问题，别让用户对着 traceback 发愣
        out["advice"] = "本地库损坏，运行 `jobradar update --force` 重新下载"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if out["jobs_db"]:
        with _open("jobs") as conn:
            env = envelope(conn, [])
            out["fields"] = q.field_coverage(conn)
            out["source_health"] = q.source_freshness(q.data_status(conn, now=now_ts()))
        out.update(data_as_of=env["data_as_of"], stale=env["stale"])
        cov = _text_coverage(data_dir())
        if cov is not None:
            out["jd_text_match"] = round(cov, 3)
        campus_city = (out["fields"] or {}).get("campus_cities")
        advice = ["数据已过期，运行 `jobradar update`"] if env["stale"] else []
        stale_sources = out["source_health"]["counts"]["stale"]
        if stale_sources:
            advice.append(f"{stale_sources} 个源超过 48 小时未成功刷新或从未成功，"
                          "其岗位下架状态可能滞后；运行 `jobradar sources --problems` 查看，"
                          "投递前打开原始链接确认；下载新快照不保证这些源已恢复")
        if cov is not None and cov < 0.9:
            advice.append(f"未下架岗位的正文行覆盖为 {cov:.0%}；来源可能未提供正文，缺失比例不能证明三库不同代")
        if campus_city is not None and campus_city < 0.25:
            advice.append(f"校园岗城市覆盖只有 {campus_city:.0%}：多数北森门户不返回城市，搜城市时结果会偏少")
        # 日期同理：覆盖率低时搜「最近截止/最近发布」会漏掉大批岗位，最好提前说清。
        for key, label in (("publish_at", "发布日期"), ("apply_end", "截止日")):
            rate = (out["fields"] or {}).get(key)
            if rate is not None and rate < 0.25:
                advice.append(f"{label}覆盖只有 {rate:.0%}：多数来源不提供，按时间排序时结果会偏少")
        out["advice"] = "；".join(advice) or "ok"
    else:
        out["advice"] = "运行 `jobradar update`"
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _doctor_robots(args) -> None:
    """逐个源检查 robots.txt。**抓新站之前必跑** —— 2026-10-26 一天内两次
    因没读全 robots 而抓了不该抓的页面（radancy 欧莱雅 351 岗、tupu360 共享域 774 岗）。"""
    from jobradar.adapters.base import make_client
    from jobradar.robots import check, source_urls
    from jobradar.sources import load_sources

    sources = load_sources(Path(args.sources))
    if not sources:
        raise SystemExit(f"没匹配到任何源（--sources {args.sources}）")
    rows = []
    with make_client() as client:
        for s in sources:
            urls = [u for u in source_urls(s.params, s.adapter) if u.startswith("http")]
            if not urls:
                rows.append({"id": s.id, "company": s.company, "verdict": "unknown",
                             "detail": "无法从 params 推断列表页 URL，需人工确认"})
                continue
            verdicts = [check(client, u) for u in urls]
            blocked = [v for v in verdicts if not v.allowed]
            rows.append({
                "id": s.id, "company": s.company,
                "verdict": "blocked" if blocked else "ok",
                "detail": str(blocked[0]) if blocked else "；".join(f"{v.url} OK" for v in verdicts),
            })
    blocked = [r for r in rows if r["verdict"] == "blocked"]
    unknown = [r for r in rows if r["verdict"] == "unknown"]
    print(f"# {len(rows)} 源：{len(rows) - len(blocked) - len(unknown)} 允许，"
          f"{len(blocked)} 被 robots 禁止，{len(unknown)} 无法判断")
    for r in blocked:
        print(f"BLOCKED  {r['id']:<28} {r['company']:<12} {r['detail']}")
    for r in unknown:
        print(f"UNKNOWN  {r['id']:<28} {r['company']:<12} {r['detail']}")
    if blocked:
        raise SystemExit(1)


def cmd_calendar(args):
    with _open("calendar") as conn:
        meta = {}
        rows = q.calendar_entries(conn, group=args.group, company=args.company, project_type=args.type,
                                  grad_year=args.grad_year, origin=args.origin, open_on=args.open_on,
                                  has_tracks=getattr(args, "has_tracks", False),
                                  has_window=getattr(args, "has_window", False),
                                  city=getattr(args, "city", None),
                                  direction=getattr(args, "direction", None),
                                  deadline_before=getattr(args, "deadline_before", None),
                                  deadline_after=getattr(args, "deadline_after", None),
                                  include_expired=getattr(args, "include_expired", False),
                                  confirmed_open_only=getattr(args, "confirmed_open_only", False),
                                  limit=args.limit, meta=meta)
        env = envelope(None, rows, as_of=q.calendar_as_of(conn), **meta)
        if not rows and args.group:
            reason = q.calendar_blocked_reason(conn, args.group)
            if reason:
                env["hint"] = f"{args.group}：{reason}。{args.group}希望你去他们的招聘页逛一逛哦~"
        if not rows and (getattr(args, "city", None) or getattr(args, "direction", None)):
            # 城市/方向是"只命中写了该字段的条目"，空结果往往不是真没有，而是字段没写。
            # 不解释的话，agent 会把这个说成"北京没有岗位"，属于事实性错误。
            env["hint"] = q.calendar_filter_advice(
                conn, city=getattr(args, "city", None),
                direction=getattr(args, "direction", None), group=args.group, company=args.company,
                project_type=args.type, grad_year=args.grad_year, origin=args.origin, open_on=args.open_on,
                include_expired=args.include_expired, has_tracks=args.has_tracks, has_window=args.has_window,
                confirmed_open_only=args.confirmed_open_only,
                deadline_before=args.deadline_before, deadline_after=args.deadline_after)
        _emit(args, env)


def cmd_stats(args):
    out = {}
    with _open("calendar", required=False) as cal_conn, _open("jobs", required=False) as jobs_conn, \
            _open("text", required=False) as text_conn:
        if cal_conn is not None:
            out["calendar"] = q.calendar_stats(cal_conn)
            out["calendar_as_of"] = q.calendar_as_of(cal_conn)
        if jobs_conn is not None:
            out["jobs"] = q.data_summary(jobs_conn, text_conn)
    if not out:
        raise SystemExit("本地没有数据：先运行 `jobradar update`。")
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_calendar_build(args):
    """开发/CI 用：从人工条目 + 数据层重建 calendar.db，可选探活全部链接。"""
    import yaml

    from jobradar.pipeline import calendar as cal
    from jobradar.sources import load_sources

    sources_dir = Path(args.sources)
    sources = load_sources(sources_dir) if sources_dir.exists() else []
    targets = yaml.safe_load(Path(args.targets).read_text(encoding="utf-8"))
    with closing(connect(Path(args.out), "calendar")) as cal_conn, \
            closing(connect(Path(args.jobs), "jobs", defer_search_index=True)) as jobs_conn:
        counts = cal.build(cal_conn, jobs_conn, manual=cal.load_manual(Path(args.entries)),
                           sources=sources, targets=targets, ts=now_ts())
        if args.check_links:
            # 探活只看状态码：超时给 8s/连接 5s（部分国内站点在 Actions 上根本连不上，等 20s 是浪费）
            with httpx.Client(timeout=httpx.Timeout(8, connect=5)) as client:
                counts["links"] = cal.check_links(cal_conn, client, ts=now_ts())
        # 导出证据必须**在 with 块里**：`jobs_conn` 由上面那个 closing() 管理，
        # 出了 with 就已经 close()，再传进去会抛 `Cannot operate on a closed database`
        # （2026-10-26 实测，`calendar-build --evidence-out` 一直是坏的）。
        if args.evidence_out:
            counts["evidence_companies"] = cal.export_job_evidence(
                jobs_conn, Path(args.evidence_out), ts=now_ts())
    print(json.dumps(counts, ensure_ascii=False))


def cmd_crawl(args):
    """开发/CI 用：抓取 sources 并写入 --out 目录下的两个库。"""
    from jobradar.pipeline.crawl import crawl
    from jobradar.sources import load_sources

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sources = load_sources(Path(args.sources))
    if args.only:
        wanted = [x.strip() for x in args.only.split(",") if x.strip()]
        known = {s.id for s in sources}
        missing = [x for x in wanted if x not in known]
        if missing:
            # --only 里写了不存在的 id 却静默跳过，是最容易把「一批源没抓」看成「抓完了」的地方
            raise SystemExit(f"--only 里这些 source id 不存在：{', '.join(missing[:10])}"
                             f"{' …' if len(missing) > 10 else ''}")
        sources = [s for s in sources if s.id in set(wanted)]
    if not sources:
        raise SystemExit(f"没匹配到任何源（--sources {args.sources}）")
    with closing(connect(out / DB_FILES["jobs"], "jobs", defer_search_index=True)) as jobs_conn, \
            closing(connect(out / DB_FILES["text"], "text", defer_search_index=True)) as text_conn:
        if getattr(args, "stale_only_hours", 0):
            due = q.due_source_ids(jobs_conn, [s.id for s in sources], hours=args.stale_only_hours, now=now_ts())
            sources = [s for s in sources if s.id in due]
        results = crawl(sources, jobs_conn, text_conn, ts=now_ts(), budget_seconds=args.budget_seconds,
                        max_workers=getattr(args, "workers", 4), source_budget=getattr(args, "source_budget", None))
    summary = {sid: {"status": r.status, "opened": r.opened, "closed": r.closed,
                     "changed": r.changed, "reason": r.reason} for sid, r in sorted(results.items())}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    failed = [s for s, r in results.items() if r.status != "ok"]
    print(f"# {len(results) - len(failed)} ok, {len(failed)} not ok", file=sys.stderr)
    if results and len(failed) == len(results):
        raise SystemExit("all sources failed")  # 让 CI 变红并通知维护者


def _version() -> str:
    """版本号唯一来源是 jobradar.__version__（pyproject 用 hatch 动态读取）。"""
    from jobradar import __version__
    return __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobradar", description="中国校招/实习/社招岗位数据查询")
    p.add_argument("--version", action="version", version=f"jobradar {_version()}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        sp.add_argument("--table", action="store_true", help="表格输出（默认 JSON）")
        return sp

    sp = add("update", cmd_update, "下载最新数据")
    sp.add_argument("--jobs-only", action="store_true", help="只下载岗位主库，不下载 JD 原文库（全文检索、对比要求需要原文库）")
    sp.add_argument("--no-index", action="store_true", help="跳过本地全文索引准备，节省空间；全文查询使用正文扫描")
    sp.add_argument("--prepare-index", action="store_true", help="激活前准备全文索引，适合频繁全文查询；会增加更新耗时和磁盘占用")
    sp.add_argument("--with-text", action="store_true", help=argparse.SUPPRESS)  # 兼容旧参数：现在默认就下载原文库
    sp.add_argument("--mirror", choices=["github", "gitee"], help="下载源（默认GitHub）；镜像状态见项目文档，失败时尝试备用源")
    sp.add_argument("--force", action="store_true", help="忽略增量比对，强制重新下载全部数据")

    sp = add("search", cmd_search, "搜索在招岗位")
    sp.add_argument("--company", help="公司名（支持简称映射；只差一个字的前缀延伸不猜，如 京东≠京东方）")
    sp.add_argument("--contains", action="store_true", help="--company 按子串匹配（会命中多家，如 --company 中国）")
    sp.add_argument("--dedupe", action=argparse.BooleanOptionalAction, default=True,
                    # 注意：argparse 对 help 文本做 % 插值，裸 `%` 会让 `search --help` 直接抛
                    # ValueError: unsupported format character（2026-10-27 实测）→ 写成 `%%`
                    help="默认折叠相同展示分组并给出variants原条数；--no-dedupe查看全部记录")
    sp.add_argument("--exclude-store", action="store_true",
                    help="排除门店/零售岗（门店/店员/导购/收银/咖啡师/店长…；喜茶、星巴克门店帖约 8 千条）")
    sp.add_argument("--category", help="职类，如 技术/产品/算法/后端")
    sp.add_argument("--city")
    sp.add_argument("--cities", nargs="+", help="多个城市取并集，不能与--city同时使用")
    sp.add_argument("--exclude-city", action="append", help="排除任一列出的城市，可重复")
    sp.add_argument("--exclude-keyword", action="append", help="排除标题字面量，可重复；不代表语义排除")
    sp.add_argument("--exclude-company", action="append", help="排除确定主体，可重复；歧义名称需澄清")
    sp.add_argument("--type", choices=["campus", "intern", "social"])
    sp.add_argument("--grad-year", type=int)
    sp.add_argument("--include-unknown-grad-year", action="store_true", help="同时保留届次未标注候选，需与--grad-year配合核实")
    sp.add_argument("--keyword", help="标题关键词")
    sp.add_argument("--text", help="全文检索：标题 + JD 原文，多个词用空格分隔（都须出现），如 \"PyTorch 大模型\"")
    sp.add_argument("--deadline-before", help="YYYY-MM-DD：只看截止日不晚于该日的岗位（找快截止的）")
    sp.add_argument("--deadline-after", help="YYYY-MM-DD：只看截止日不早于该日的岗位（排除已过期）")
    sp.add_argument("--include-closed", action="store_true", help="包含已下架或已明确到期的历史岗位")
    sp.add_argument("--limit", type=int, default=50)

    sp = add("show", cmd_show, "岗位详情（含 JD 原文，若已下载）")
    sp.add_argument("job_id")

    sp = add("diff", cmd_diff, "最近 N 天的新开/下架/变更")
    sp.add_argument("--days", type=int, default=7)
    sp.add_argument("--company", help="公司名；与 --by 一起用时会真的只统计这家公司")
    sp.add_argument("--contains", action="store_true", help="--company 按子串匹配")
    sp.add_argument("--types", help="逗号分隔：open,close,change,reopen")
    sp.add_argument("--by", choices=["category"], help="按维度聚合：category = 新增岗位按职类统计")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("compare", cmd_compare, "取多家公司同类岗位的 JD 原文，供对比")
    sp.add_argument("companies", nargs="+")
    sp.add_argument("--category", help="职类，见 skill references/fields.md")
    sp.add_argument("--keyword", help="标题关键词，如 研发")
    sp.add_argument("--text", help="JD 全文检索词，如 论文；与 --keyword 不同，它在职责/要求原文里找")
    sp.add_argument("--per-company", type=int, default=5)
    sp.add_argument("--city", help="所有公司统一按该城市筛选")
    sp.add_argument("--type", choices=["campus", "intern", "social"])
    sp.add_argument("--grad-year", type=int)

    sp = add("trends", cmd_trends, "某公司在招岗位数随时间变化")
    sp.add_argument("company")
    sp.add_argument("--step-days", type=int, default=7)

    sp = add("calendar", cmd_calendar, "招聘日历：各公司批次、网申时间、投递入口（含抓不到 JD 的大厂）")
    sp.add_argument("--group", help="集团，如 阿里巴巴")
    sp.add_argument("--company", help="具体公司/产品，如 飞猪")
    sp.add_argument("--type", help="项目类型（子串匹配），如 秋招 / 提前批 / 实习 / 社招")
    sp.add_argument("--grad-year", type=int)
    sp.add_argument("--origin", choices=["manual", "auto"], help="manual=人工编辑，auto=数据层自动生成")
    sp.add_argument("--include-expired", action="store_true", help="包含已明确截止的历史批次（默认自动隐藏）")
    sp.add_argument("--open-on", help="YYYY-MM-DD：该日可能在投的（没写起止的条目也会返回，带 window_status=unknown）")
    sp.add_argument("--confirmed-open-only", action="store_true", help="与--open-on配合，只返回明确完整批次日期窗口，仍需核实原站")
    sp.add_argument("--has-tracks", action="store_true", help="只看有方向（track）的条目")
    sp.add_argument("--has-window", action="store_true", help="只看写了网申起止的条目")
    sp.add_argument("--city", help="城市，如 北京 / 杭州（只命中写了城市的条目）")
    sp.add_argument("--direction", help="方向，如 技术类 / 产品类 / 职能类（只命中写了方向的条目）")
    sp.add_argument("--deadline-before", help="YYYY-MM-DD：截止日不晚于该日（找快截止的）")
    sp.add_argument("--deadline-after", help="YYYY-MM-DD：截止日不早于该日（排除已过期）")
    sp.add_argument("--limit", type=int, default=100)

    add("stats", cmd_stats, "覆盖率：目标公司的日历覆盖、JD 覆盖、岗位与正文数量")
    sp = add("sources", cmd_sources, "各数据源的抓取状态与新鲜度")
    sp.add_argument("--problems", action="store_true", help="只看上次未成功或已过期的源")
    sp.add_argument("--summary", action="store_true", help="只给计数与有问题的源（默认最多20条异常详情，其余按需展开）")
    sp = add("doctor", cmd_doctor, "检查本地数据是否存在、是否过期")
    sp.add_argument("--robots", action="store_true",
                    help="逐个源检查 robots.txt 是否允许抓它的列表页（抓新站前必跑）")
    sp.add_argument("--sources", default="sources", help="--robots 用的源目录")

    sp = add("crawl", cmd_crawl, "（开发/CI）抓取并写库")
    sp.add_argument("--sources", default="sources")
    sp.add_argument("--out", default="data")
    sp.add_argument("--only", help="逗号分隔的 source id")
    sp.add_argument("--budget-seconds", type=float, default=None,
                    help="整轮采集的时间预算；超出后剩余源标记为失败（daily 用，防止拖到 workflow 上限）")
    sp.add_argument("--workers", type=int, default=4,
                    help="并行站点数（按「适配器+站点」分组，同站点仍串行）")
    sp.add_argument("--source-budget", type=float, default=None, help="单源完整采集的时间预算；超时丢弃本源部分结果")
    sp.add_argument("--stale-only-hours", type=int, default=0, help="只刷新最近成功时间超过指定小时或从未成功的源；0为全部")

    sp = add("calendar-build", cmd_calendar_build, "（开发/CI）重建招聘日历库")
    sp.add_argument("--jobs", default="data/jobs.db")
    sp.add_argument("--out", default="data/calendar.db")
    sp.add_argument("--entries", default="calendar/entries")
    sp.add_argument("--sources", default="sources")
    sp.add_argument("--targets", default="targets/top_companies.yaml")
    sp.add_argument("--check-links", action="store_true", help="对全部链接各发一次探活请求")
    sp.add_argument("--evidence-out", default=None,
                    help="把 jobs.db 里的结构化职位证据（城市/截止日/届次）导成 JSONL，"
                         "供日历生成使用（把接口字段的城市/截止日带进日历）")
    return p


def _configure_stdio():
    """Windows 终端默认 GBK/CP936，岗位标题或 JD 里的非常规字符（如零宽空格 U+200B）
    会让 print 直接抛 UnicodeEncodeError，整条命令失败。

    - 输出到管道/文件（agent 读的就是这个）：统一 UTF-8，便于下游解析。
    - 输出到终端：保留系统编码（中文照常显示），个别字符降级为 ?，不再崩溃。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # 非标准流（测试替身、已关闭的管道）直接跳过


def _ensure_utf8_streams() -> None:
    """把 stdout/stderr 切成 UTF-8（errors=replace）。

    背景：Windows 英文版控制台默认 cp1252，打印中文 JSON 会直接 UnicodeEncodeError
    （2026-10-23 CI 的 windows-latest 就是这样红的）。中文 Windows 是 cp936 不受影响，
    但没理由让英文 locale 的用户用不了。
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if enc not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — 某些被重定向的流不支持 reconfigure
            pass


def main(argv=None):
    _ensure_utf8_streams()
    _configure_stdio()
    args = build_parser().parse_args(argv)
    try:
        with snapshot() if args.cmd not in {"update", "crawl", "calendar-build"} else nullcontext():
            args.fn(args)
    except NoData as e:
        raise SystemExit(str(e)) from None
    except OSError as e:
        raise SystemExit(f"本地文件操作失败（{type(e).__name__}）；既有快照保持可用，请检查空间和权限") from None
    except sqlite3.DatabaseError as e:
        # 兜底：local.open_db 之外的路径（写库、只读库、锁库）漏出来的 sqlite 错误
        # 也不能让用户对着 traceback 发愣。
        raise SystemExit(f"本地数据读取失败（{e}）。先运行 `jobradar doctor`；"
                         "若提示损坏，用 `jobradar update --force` 重新下载。") from None
    except ValueError as e:
        raise SystemExit(f"参数或数据无效：{e}") from None


if __name__ == "__main__":
    main()
