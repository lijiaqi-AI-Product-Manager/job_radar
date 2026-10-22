"""jobradar 命令行。所有查询都调用 core/queries.py；输出默认 JSON（给 agent），--table 输出表格（给人）。

每个查询结果都带 data_as_of（数据截至时间），skill 要求 agent 在回答里引用它。
"""

import argparse
import gzip
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, nullcontext
from datetime import timedelta
from pathlib import Path

import httpx

from jobradar.core import queries as q
from jobradar.local import DB_FILES, RELEASE_TAG, REPO, NoData, asset_urls, db, envelope, home
from jobradar.store.migrate import connect
from jobradar.timeutil import FMT, now_ts, parse_ts


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
        print(f"# data_as_of: {payload.get('data_as_of')}  ({len(rows)} 条)")
        if rows and "title" in rows[0]:  # 岗位 / 事件
            for r in rows:
                cities = "/".join(r.get("cities") or [])
                print(" | ".join(str(x) for x in (
                    r.get("company"), r.get("title"), cities, r.get("type") or r.get("recruit_type"),
                    r.get("grad_year") or "", r.get("ts") or r.get("first_seen"), r.get("url"))))
        elif rows:  # 其他（数据源状态、趋势）：按字段输出
            cols = list(rows[0].keys())
            print(" | ".join(cols))
            for r in rows:
                print(" | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


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


def _now() -> float:
    return time.monotonic()


def _fetch(client: httpx.Client, url: str, headers: dict, dest_dir: Path) -> Path | None:
    """下载到临时文件；404 返回 None。

    先关闭文件再删除：Windows 上删除仍被打开的文件会报 WinError 32。
    慢镜像要尽早放弃：read timeout 只约束"多久没收到字节"，对每秒滴几 KB 的连接无效
    （2026-10-22 实测 Gitee 一次 update 卡了 14 分钟还没完），所以按吞吐与总时长兜底。
    """
    fd, name = tempfile.mkstemp(dir=dest_dir, suffix=".part")
    tmp = Path(name)
    not_found = False
    started, received, slow_checked = _now(), 0, False
    try:
        with os.fdopen(fd, "wb") as out, client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 404:
                not_found = True
            else:
                resp.raise_for_status()
                size = int(resp.headers.get("content-length") or 0)
                for chunk in resp.iter_bytes():
                    out.write(chunk)
                    received += len(chunk)
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
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if not_found:
        tmp.unlink(missing_ok=True)
        return None
    return tmp


def _install(tmp: Path, name: str, gz: bool, dest: Path):
    """解压（若为 .gz）并校验 SQLite 完整性后替换目标文件。"""
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
    con = sqlite3.connect(tmp)
    try:
        ok = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    except sqlite3.DatabaseError:
        ok = False
    finally:
        con.close()  # 必须关闭：否则 Windows 上 replace 会失败（WinError 32）
    if not ok:
        tmp.unlink()
        raise ValueError("不是有效的数据库")
    tmp.replace(dest)


def _download(name: str, dest: Path, client: httpx.Client | None = None, prefer: str | None = None) -> str:
    """依次尝试各镜像，每个镜像先取压缩版 <name>.gz，没有再取原文件。返回实际使用的镜像名。"""
    client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:  # 私有仓库：只能走 GitHub API
        found = _github_api_asset(name, client, token)
        if found is None:
            raise SystemExit(f"Release {RELEASE_TAG} 中没有 {name}")
        tmp = _fetch(client, found[0], found[1], dest.parent)
        if tmp is None:
            raise SystemExit(f"下载 {name} 失败（404）")
        try:
            _install(tmp, name, False, dest)
        except ValueError as e:
            raise SystemExit(f"下载的 {name} {e}") from None
        return "github"
    errors, invalid = [], False
    for (mirror, url), (_, gz_url) in zip(asset_urls(name, prefer), asset_urls(name + ".gz", prefer), strict=True):
        for candidate, gz in ((gz_url, True), (url, False)):
            try:
                tmp = _fetch(client, candidate, {}, dest.parent)
                if tmp is None:
                    continue
                _install(tmp, name, gz, dest)
                return mirror
            except httpx.HTTPError as e:
                errors.append(f"{mirror}: {type(e).__name__}")
                break  # 该镜像不可达，换下一个
            except ValueError as e:
                errors.append(f"{mirror}: {e}")
                invalid = True
    if invalid:
        raise SystemExit(f"下载的 {name} 不是有效的数据库（{'; '.join(errors)}）")
    raise SystemExit(f"下载 {name} 失败（{'; '.join(errors) or '404'}）。"
                     "国内网络可试 `jobradar update --mirror gitee`；若仓库尚未公开，请设置环境变量 GITHUB_TOKEN 后重试。")


def cmd_update(args):
    home().mkdir(parents=True, exist_ok=True)
    kinds = ["jobs", "calendar"] if args.jobs_only else ["jobs", "text", "calendar"]
    used: dict[str, str | None] = {}
    errors: dict[str, SystemExit] = {}
    # 三个库并行下载：总耗时从"三个文件之和"降到"最慢的那个"（jd_text 最大）
    with ThreadPoolExecutor(max_workers=len(kinds)) as pool:
        futures = [(k, pool.submit(_download, DB_FILES[k], home() / DB_FILES[k], prefer=args.mirror))
                   for k in kinds]
        for k, fut in futures:
            try:
                used[k] = fut.result()
            except SystemExit as e:
                errors[k] = e
    if "jobs" in errors or "text" in errors:  # 日历库在旧版发布中不存在：缺失不影响岗位数据
        raise errors.get("jobs") or errors["text"]
    used["calendar"] = None if "calendar" in errors else used.get("calendar")
    with _open("jobs") as conn:
        print(json.dumps({"updated": kinds, "mirror": {k: used.get(k) for k in kinds},
                          "data_as_of": q.data_as_of(conn), "home": str(home())}, ensure_ascii=False))


def cmd_search(args):
    text_cm = _open("text", required=False) if args.text else nullcontext(None)
    with _open("jobs") as conn, text_cm as text:
        if args.text and text is None:
            raise SystemExit("全文检索需要 JD 原文库：先运行 `jobradar update`")
        rows = q.search_jobs(conn, company=args.company, category=args.category, city=args.city,
                             recruit_type=args.type, grad_year=args.grad_year, keyword=args.keyword,
                             text=args.text, text_conn=text, include_closed=args.include_closed, limit=args.limit)
        _emit(args, envelope(conn, rows))


def cmd_show(args):
    with _open("jobs") as conn, _open("text", required=False) as text:
        job = q.get_job(conn, text, args.job_id)
        _emit(args, envelope(conn, [job] if job else [], found=job is not None))


def cmd_diff(args):
    with _open("jobs") as conn:
        since = (parse_ts(now_ts()) - timedelta(days=args.days)).strftime(FMT)
        if args.by:
            rows = q.new_jobs_by_category(conn, since=since, limit=args.limit)
            _emit(args, envelope(conn, rows, since=since, by=args.by))
            return
        rows = q.recent_changes(conn, since=since, company=args.company,
                                types=args.types.split(",") if args.types else None, limit=args.limit)
        _emit(args, envelope(conn, rows, since=since))


def cmd_compare(args):
    with _open("jobs") as conn, _open("text", required=False) as text_conn:
        if text_conn is None:
            raise SystemExit("对比需要 JD 原文库：先运行 `jobradar update`。")
        if not args.category and not args.keyword and not args.text:
            raise SystemExit("compare 需要 --category、--keyword 或 --text")
        out = q.compare_roles(conn, text_conn, args.companies, args.category, keyword=args.keyword,
                              text=args.text, per_company=args.per_company)
        _emit(args, envelope(conn, out, category=args.category, keyword=args.keyword, text=args.text,
                              not_found=[c for c, v in out.items() if not v]))


def cmd_trends(args):
    with _open("jobs") as conn:
        rows = q.company_trend(conn, args.company, until=now_ts(), step_days=args.step_days)
        _emit(args, envelope(conn, rows, company=args.company))


def cmd_sources(args):
    with _open("jobs") as conn:
        rows = q.data_status(conn, now=now_ts())
        _emit(args, envelope(conn, rows, failing=[r["source_id"] for r in rows if r["stale"]]))


def cmd_doctor(args):
    out = {"home": str(home()), "jobs_db": (home() / DB_FILES["jobs"]).exists(),
           "jd_text_db": (home() / DB_FILES["text"]).exists(),
           "calendar_db": (home() / DB_FILES["calendar"]).exists()}
    if out["jobs_db"]:
        with _open("jobs") as conn:
            env = envelope(conn, [])
        out.update(data_as_of=env["data_as_of"], stale=env["stale"])
        out["advice"] = "数据已过期，运行 `jobradar update`" if env["stale"] else "ok"
    else:
        out["advice"] = "运行 `jobradar update`"
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_calendar(args):
    with _open("calendar") as conn:
        rows = q.calendar_entries(conn, group=args.group, company=args.company, project_type=args.type,
                                  grad_year=args.grad_year, origin=args.origin, open_on=args.open_on, limit=args.limit)
        _emit(args, envelope(None, rows, as_of=q.calendar_as_of(conn)))


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
            closing(connect(Path(args.jobs), "jobs")) as jobs_conn:
        counts = cal.build(cal_conn, jobs_conn, manual=cal.load_manual(Path(args.entries)),
                           sources=sources, targets=targets, ts=now_ts())
        if args.check_links:
            with httpx.Client(timeout=httpx.Timeout(20, connect=10)) as client:
                counts["links"] = cal.check_links(cal_conn, client, ts=now_ts())
    print(json.dumps(counts, ensure_ascii=False))


def cmd_crawl(args):
    """开发/CI 用：抓取 sources 并写入 --out 目录下的两个库。"""
    from jobradar.pipeline.crawl import crawl
    from jobradar.sources import load_sources

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sources = load_sources(Path(args.sources))
    if args.only:
        sources = [s for s in sources if s.id in set(args.only.split(","))]
    with closing(connect(out / DB_FILES["jobs"], "jobs")) as jobs_conn, \
            closing(connect(out / DB_FILES["text"], "text")) as text_conn:
        results = crawl(sources, jobs_conn, text_conn, ts=now_ts())
    summary = {sid: {"status": r.status, "opened": r.opened, "closed": r.closed,
                     "changed": r.changed, "reason": r.reason} for sid, r in sorted(results.items())}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    failed = [s for s, r in results.items() if r.status != "ok"]
    print(f"# {len(results) - len(failed)} ok, {len(failed)} not ok", file=sys.stderr)
    if results and len(failed) == len(results):
        raise SystemExit("all sources failed")  # 让 CI 变红并通知维护者


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobradar", description="中国校招/实习/社招岗位数据查询")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        sp.add_argument("--table", action="store_true", help="表格输出（默认 JSON）")
        return sp

    sp = add("update", cmd_update, "下载最新数据")
    sp.add_argument("--jobs-only", action="store_true", help="只下载岗位主库，不下载 JD 原文库（全文检索、对比要求需要原文库）")
    sp.add_argument("--with-text", action="store_true", help=argparse.SUPPRESS)  # 兼容旧参数：现在默认就下载原文库
    sp.add_argument("--mirror", choices=["github", "gitee"], help="下载源；国内网络建议 gitee。失败时自动换另一个")

    sp = add("search", cmd_search, "搜索在招岗位")
    sp.add_argument("--company")
    sp.add_argument("--category", help="职类，如 技术/产品/算法/后端")
    sp.add_argument("--city")
    sp.add_argument("--type", choices=["campus", "intern", "social"])
    sp.add_argument("--grad-year", type=int)
    sp.add_argument("--keyword", help="标题关键词")
    sp.add_argument("--text", help="全文检索：标题 + JD 原文，多个词用空格分隔（都须出现），如 \"PyTorch 大模型\"")
    sp.add_argument("--include-closed", action="store_true")
    sp.add_argument("--limit", type=int, default=50)

    sp = add("show", cmd_show, "岗位详情（含 JD 原文，若已下载）")
    sp.add_argument("job_id")

    sp = add("diff", cmd_diff, "最近 N 天的新开/下架/变更")
    sp.add_argument("--days", type=int, default=7)
    sp.add_argument("--company")
    sp.add_argument("--types", help="逗号分隔：open,close,change,reopen")
    sp.add_argument("--by", choices=["category"], help="按维度聚合：category = 新增岗位按职类统计")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("compare", cmd_compare, "取多家公司同类岗位的 JD 原文，供对比")
    sp.add_argument("companies", nargs="+")
    sp.add_argument("--category", help="职类，见 skill references/fields.md")
    sp.add_argument("--keyword", help="标题关键词，如 研发")
    sp.add_argument("--text", help="JD 全文检索词，如 论文；与 --keyword 不同，它在职责/要求原文里找")
    sp.add_argument("--per-company", type=int, default=5)

    sp = add("trends", cmd_trends, "某公司在招岗位数随时间变化")
    sp.add_argument("company")
    sp.add_argument("--step-days", type=int, default=7)

    sp = add("calendar", cmd_calendar, "招聘日历：各公司批次、网申时间、投递入口（含抓不到 JD 的大厂）")
    sp.add_argument("--group", help="集团，如 阿里巴巴")
    sp.add_argument("--company", help="具体公司/产品，如 飞猪")
    sp.add_argument("--type", help="项目类型（子串匹配），如 秋招 / 提前批 / 实习 / 社招")
    sp.add_argument("--grad-year", type=int)
    sp.add_argument("--origin", choices=["manual", "auto"], help="manual=人工编辑，auto=数据层自动生成")
    sp.add_argument("--open-on", help="YYYY-MM-DD：只看该日网申开放中的")
    sp.add_argument("--limit", type=int, default=100)

    add("stats", cmd_stats, "覆盖率：目标公司的日历覆盖、JD 覆盖、岗位与正文数量")
    add("sources", cmd_sources, "各数据源的抓取状态与新鲜度")
    add("doctor", cmd_doctor, "检查本地数据是否存在、是否过期")

    sp = add("crawl", cmd_crawl, "（开发/CI）抓取并写库")
    sp.add_argument("--sources", default="sources")
    sp.add_argument("--out", default="data")
    sp.add_argument("--only", help="逗号分隔的 source id")

    sp = add("calendar-build", cmd_calendar_build, "（开发/CI）重建招聘日历库")
    sp.add_argument("--jobs", default="data/jobs.db")
    sp.add_argument("--out", default="data/calendar.db")
    sp.add_argument("--entries", default="calendar/entries")
    sp.add_argument("--sources", default="sources")
    sp.add_argument("--targets", default="targets/top_companies.yaml")
    sp.add_argument("--check-links", action="store_true", help="对全部链接各发一次请求探活")
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


def main(argv=None):
    _configure_stdio()
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
