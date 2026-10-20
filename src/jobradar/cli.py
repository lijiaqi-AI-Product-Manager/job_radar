"""jobradar 命令行。所有查询都调用 core/queries.py；输出默认 JSON（给 agent），--table 输出表格（给人）。

每个查询结果都带 data_as_of（数据截至时间），skill 要求 agent 在回答里引用它。
"""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import httpx

from jobradar.core import queries as q
from jobradar.local import DB_FILES, RELEASE_TAG, REPO, NoData, envelope, home, open_db, release_url
from jobradar.store.migrate import connect
from jobradar.timeutil import FMT, now_ts, parse_ts


def _open(kind: str, required: bool = True):
    try:
        return open_db(kind, required)
    except NoData as e:
        raise SystemExit(str(e)) from e


def _emit(args, payload: dict):
    if getattr(args, "table", False) and isinstance(payload.get("results"), list):
        rows = payload["results"]
        print(f"# data_as_of: {payload.get('data_as_of')}  ({len(rows)} 条)")
        for r in rows:
            cities = "/".join(r.get("cities") or [])
            print(" | ".join(str(x) for x in (
                r.get("company"), r.get("title"), cities, r.get("recruit_type"), r.get("grad_year") or "",
                r.get("ts") or r.get("first_seen"), r.get("url"))))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _asset_request(name: str, client: httpx.Client) -> tuple[str, dict]:
    """公开仓库：直接下载 Release 资源（可走 JOBRADAR_MIRROR）。
    设置了 GITHUB_TOKEN/GH_TOKEN（例如仓库尚未公开时）：通过 API 带鉴权下载。"""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return release_url(name), {}
    auth = {"Authorization": f"Bearer {token}"}
    r = client.get(f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}", headers=auth)
    r.raise_for_status()
    asset = next((a for a in r.json().get("assets", []) if a["name"] == name), None)
    if asset is None:
        raise SystemExit(f"Release {RELEASE_TAG} 中没有 {name}")
    return asset["url"], {**auth, "Accept": "application/octet-stream"}


def _download(name: str, dest: Path, client: httpx.Client | None = None):
    client = client or httpx.Client(timeout=120, follow_redirects=True)
    url, headers = _asset_request(name, client)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 404:
                Path(tmp.name).unlink(missing_ok=True)
                raise SystemExit(f"下载 {name} 失败（404）。若仓库尚未公开，请设置环境变量 GITHUB_TOKEN 后重试。")
            resp.raise_for_status()
            for chunk in resp.iter_bytes():
                tmp.write(chunk)
    tmp_path = Path(tmp.name)
    try:
        ok = sqlite3.connect(tmp_path).execute("PRAGMA quick_check").fetchone()[0] == "ok"
    except sqlite3.DatabaseError:
        ok = False
    if not ok:
        tmp_path.unlink()
        raise SystemExit(f"下载的 {name} 不是有效的数据库")
    tmp_path.replace(dest)


def cmd_update(args):
    home().mkdir(parents=True, exist_ok=True)
    kinds = ["jobs", "text"] if args.with_text else ["jobs"]
    for k in kinds:
        _download(DB_FILES[k], home() / DB_FILES[k])
    conn = _open("jobs")
    print(json.dumps({"updated": kinds, "data_as_of": q.data_as_of(conn), "home": str(home())},
                     ensure_ascii=False))


def cmd_search(args):
    conn = _open("jobs")
    rows = q.search_jobs(conn, company=args.company, category=args.category, city=args.city,
                         recruit_type=args.type, grad_year=args.grad_year, keyword=args.keyword,
                         include_closed=args.include_closed, limit=args.limit)
    _emit(args, envelope(conn, rows))


def cmd_show(args):
    conn = _open("jobs")
    job = q.get_job(conn, _open("text", required=False), args.job_id)
    _emit(args, envelope(conn, [job] if job else [], found=job is not None))


def cmd_diff(args):
    conn = _open("jobs")
    since = (parse_ts(now_ts()) - timedelta(days=args.days)).strftime(FMT)
    rows = q.recent_changes(conn, since=since, company=args.company,
                            types=args.types.split(",") if args.types else None, limit=args.limit)
    _emit(args, envelope(conn, rows, since=since))


def cmd_compare(args):
    conn = _open("jobs")
    text = _open("text", required=False)
    if text is None:
        raise SystemExit("对比需要 JD 原文库：先运行 `jobradar update --with-text`。")
    if not args.category and not args.keyword:
        raise SystemExit("compare 需要 --category 或 --keyword")
    out = q.compare_roles(conn, text, args.companies, args.category, keyword=args.keyword,
                          per_company=args.per_company)
    _emit(args, envelope(conn, out, category=args.category, keyword=args.keyword,
                          not_found=[c for c, v in out.items() if not v]))


def cmd_trends(args):
    conn = _open("jobs")
    rows = q.company_trend(conn, args.company, until=now_ts(), step_days=args.step_days)
    _emit(args, envelope(conn, rows, company=args.company))


def cmd_sources(args):
    conn = _open("jobs")
    rows = q.data_status(conn, now=now_ts())
    _emit(args, envelope(conn, rows, failing=[r["source_id"] for r in rows if r["stale"]]))


def cmd_doctor(args):
    out = {"home": str(home()), "jobs_db": (home() / DB_FILES["jobs"]).exists(),
           "jd_text_db": (home() / DB_FILES["text"]).exists()}
    if out["jobs_db"]:
        conn = _open("jobs")
        env = envelope(conn, [])
        out.update(data_as_of=env["data_as_of"], stale=env["stale"])
        out["advice"] = "数据已过期，运行 `jobradar update`" if env["stale"] else "ok"
    else:
        out["advice"] = "运行 `jobradar update`（对比岗位要求另加 --with-text）"
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_crawl(args):
    """开发/CI 用：抓取 sources 并写入 --out 目录下的两个库。"""
    from jobradar.pipeline.crawl import crawl
    from jobradar.sources import load_sources

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sources = load_sources(Path(args.sources))
    if args.only:
        sources = [s for s in sources if s.id in set(args.only.split(","))]
    jobs_conn = connect(out / DB_FILES["jobs"], "jobs")
    text_conn = connect(out / DB_FILES["text"], "text")
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
    sp.add_argument("--with-text", action="store_true", help="同时下载 JD 原文库（对比岗位要求需要）")

    sp = add("search", cmd_search, "搜索在招岗位")
    sp.add_argument("--company")
    sp.add_argument("--category", help="职类，如 技术/产品/算法/后端")
    sp.add_argument("--city")
    sp.add_argument("--type", choices=["campus", "intern", "social"])
    sp.add_argument("--grad-year", type=int)
    sp.add_argument("--keyword", help="标题关键词")
    sp.add_argument("--include-closed", action="store_true")
    sp.add_argument("--limit", type=int, default=50)

    sp = add("show", cmd_show, "岗位详情（含 JD 原文，若已下载）")
    sp.add_argument("job_id")

    sp = add("diff", cmd_diff, "最近 N 天的新开/下架/变更")
    sp.add_argument("--days", type=int, default=7)
    sp.add_argument("--company")
    sp.add_argument("--types", help="逗号分隔：open,close,change,reopen")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("compare", cmd_compare, "取多家公司同类岗位的 JD 原文，供对比")
    sp.add_argument("companies", nargs="+")
    sp.add_argument("--category", help="职类，见 skill references/fields.md")
    sp.add_argument("--keyword", help="标题关键词，如 研发")
    sp.add_argument("--per-company", type=int, default=5)

    sp = add("trends", cmd_trends, "某公司在招岗位数随时间变化")
    sp.add_argument("company")
    sp.add_argument("--step-days", type=int, default=7)

    add("sources", cmd_sources, "各数据源的抓取状态与新鲜度")
    add("doctor", cmd_doctor, "检查本地数据是否存在、是否过期")

    sp = add("crawl", cmd_crawl, "（开发/CI）抓取并写库")
    sp.add_argument("--sources", default="sources")
    sp.add_argument("--out", default="data")
    sp.add_argument("--only", help="逗号分隔的 source id")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
