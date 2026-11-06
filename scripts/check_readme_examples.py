"""离线校验文档命令；机会示例必须有结果，历史窗口允许真实的零变更。"""

import argparse
import contextlib
import inspect
import io
import json
import re
import shlex
import sqlite3
import sys
from calendar import monthrange
from contextlib import ExitStack, closing
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.cli import build_parser  # noqa: E402
from jobradar.core import queries as q  # noqa: E402
from jobradar.timeutil import shanghai_date  # noqa: E402


def documented_commands(root):
    paths = sorted(root.glob("README*.md"))
    skill = root / "skill/jobradar/SKILL.md"
    if skill.is_file():
        paths.append(skill)
    found = {}
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            fragments = [line.strip(), *re.findall(r"`([^`\n]+)`", line)]
            for text in fragments:
                text = re.sub(r"^(?:\$\s+|uv run\s+)", "", text)
                if not re.match(r"^jobradar\s+(?:[a-z]|--)", text):
                    continue
                command = text.strip()
                location = f"{path.relative_to(root).as_posix()}:{number}"
                found.setdefault(command, []).append(location)
    return [(command, sorted(set(locations))) for command, locations in found.items()]


def _kwargs(function, arguments, rename=None):
    values = vars(arguments)
    rename = rename or {}
    return {rename.get(key, key): value for key, value in values.items()
            if rename.get(key, key) in inspect.signature(function).parameters}


def _query(arguments, jobs, texts, calendar, *, meta=None):
    command = arguments.cmd
    meta = {} if meta is None else meta
    if command == "search":
        kwargs = _kwargs(q.search_jobs, arguments, {"type":"recruit_type", "exclude_city":"exclude_cities",
                           "exclude_keyword":"exclude_keywords", "exclude_company":"exclude_companies",
                           "exclude_category":"exclude_categories"})
        q.search_jobs(jobs, text_conn=texts, meta=meta, **kwargs)
        return meta["total"]
    if command == "calendar":
        q.calendar_entries(calendar, meta=meta, **_kwargs(q.calendar_entries, arguments, {"type":"project_type"}))
        return meta["total"]
    if command == "show":
        return int(q.get_job(jobs, texts, arguments.job_id) is not None)
    if command == "compare":
        result = q.compare_roles(jobs, texts, **_kwargs(q.compare_roles, arguments,
                                   {"type":"recruit_type", "exclude_category":"exclude_categories"}))
        return sum(map(len, result.values())) if all(result.values()) else 0
    if command == "diff":
        since = q.lookback_since(arguments.days)
        if arguments.by:
            return len(q.new_jobs_by_category(jobs, since=since, company=arguments.company,
                                              contains=arguments.contains, limit=arguments.limit, meta=meta))
        return len(q.recent_changes(jobs, since=since, company=arguments.company, contains=arguments.contains,
                                    limit=arguments.limit, types=arguments.types.split(",") if arguments.types else None,
                                    meta=meta))
    if command == "trends":
        return len(q.company_trend(jobs, arguments.company, until=q.now_ts(), step_days=arguments.step_days))
    if command == "stats":
        return q.data_summary(jobs, texts)["open_jobs"]
    if command in {"sources", "doctor"}:
        return len(q.data_status(jobs, now=q.now_ts()))
    return None


def check_examples(home, *, root=ROOT):
    """以只读连接调用共用查询层；不调用文档命令中的下载、采集或写库函数。"""
    rows = []
    parser = build_parser()
    today = date.fromisoformat(shanghai_date(q.now_ts()))
    month_end = today.replace(day=monthrange(today.year,today.month)[1]).isoformat()
    replacements = {"<今天日期>":today.isoformat(), "<日期>":month_end, "<本月末>":month_end}
    with ExitStack() as stack:
        connections = []
        for name in ("jobs.db", "jd_text.db", "calendar.db"):
            conn = stack.enter_context(closing(sqlite3.connect((home / name).resolve().as_uri()+"?mode=ro", uri=True)))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            if name == "jd_text.db":
                from jobradar.compact_text import register_compact_functions
                register_compact_functions(conn)
            connections.append(conn)
        jobs, texts, calendar = connections
        first = q.search_jobs(jobs, limit=1)
        if first:
            replacements.update({"<job_id>":first[0]["id"], "<jd_company>":first[0]["company"]})
        for command, locations in documented_commands(root):
            row = {"command":command, "locations":locations, "ok":False, "count":None, "mode":"query"}
            try:
                tokens = shlex.split(command, comments=True)[1:]
                tokens = [replacements.get(token, token) for token in tokens]
                if any(re.fullmatch(r"<[^>]+>", token) for token in tokens):
                    raise ValueError("示例有未绑定的占位符")
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    try:
                        arguments = parser.parse_args(tokens)
                    except SystemExit as error:
                        if error.code == 0:
                            row.update(ok=True, mode="syntax")
                            rows.append(row)
                            continue
                        raise ValueError("示例参数不受支持") from None
                query_meta = {}
                count = _query(arguments, jobs, texts, calendar, meta=query_meta)
                row.update(count=count, mode="syntax" if count is None else "query", ok=count is None or count > 0)
                if arguments.cmd == "diff":
                    match = query_meta.get("company_match")
                    known_company = not arguments.company or bool(match and match.get("matched"))
                    row.update(mode="history", ok=known_company,
                               outcome="events_found" if count else "no_events_in_window")
                    if match is not None:
                        row["company_match"] = match
                    if not known_company:
                        row.update(ok=False, outcome="unresolved_company", error="示例公司未确定匹配收录主体")
            except (OSError, ValueError, TypeError, sqlite3.DatabaseError) as error:
                row["error"] = str(error)
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args()
    rows = check_examples(arguments.home, root=arguments.root)
    print(json.dumps({"examples":rows, "passed":sum(r["ok"] for r in rows), "total":len(rows)}, ensure_ascii=False, indent=2))
    return int(not rows or any(not r["ok"] for r in rows))


if __name__ == "__main__":
    sys.exit(main())
