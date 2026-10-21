"""从 jobs.db 生成周报（Markdown）：本周新增/下架、新增最多的公司与职类、校招存量。
数字全部来自数据库查询；"本周"指 until 之前 7 天。

用法：python scripts/weekly_report.py data/jobs.db [--until 2026-10-26T00:00:00Z]
"""

import argparse
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.core.queries import dead_links  # noqa: E402
from jobradar.timeutil import FMT, now_ts, parse_ts  # noqa: E402


def link_section(cal_conn) -> list[str]:
    rows = dead_links(cal_conn, include_errors=True)
    out = ["", "## 投递链接探活", ""]
    if not rows:
        return out + ["全部投递/JD/来源链接本周探活正常。"]
    out += ["🔴 = 链接已失效（404/410），⚠️ = 访问异常（超时/5xx/403 等，可能是临时问题）。", "",
            "| 状态 | 链接 | HTTP | 首次失败 | 涉及条目 |", "|---|---|---|---|---|"]
    for r in rows:
        mark = "🔴" if r["status"] == "dead" else "⚠️"
        out.append(f"| {mark} | {mark} {r['url']} | {r['http_status'] or '-'} | {(r['first_failed_at'] or '')[:10]} "
                   f"| {', '.join(r['entries']) or '-'} |")
    return out


def build(conn: sqlite3.Connection, until: str, cal_conn=None) -> str:
    since = (parse_ts(until) - timedelta(days=7)).strftime(FMT)
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    rows = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731

    first_ts = one("SELECT MIN(ts) FROM source_run WHERE status='ok'")
    opened = one("SELECT COUNT(*) FROM job_event WHERE type='open' AND ts>=? AND ts<?", since, until)
    closed = one("SELECT COUNT(*) FROM job_event WHERE type='close' AND ts>=? AND ts<?", since, until)
    open_now = one("SELECT COUNT(*) FROM job WHERE closed_at IS NULL")
    companies = one("SELECT COUNT(DISTINCT company_id) FROM job WHERE closed_at IS NULL")
    campus = rows("""SELECT recruit_type, COUNT(*) FROM job WHERE closed_at IS NULL GROUP BY 1""")

    labels = {"campus": "校招", "intern": "实习", "social": "社招"}
    mix = "、".join(f"{labels[t]} {n}" for t, n in campus)
    out = [f"# 岗位周报：{since[:10]} — {until[:10]}", "",
           f"数据截至 {until}（UTC）。覆盖 {companies} 家公司，当前在招 {open_now} 个岗位（{mix}）。",
           f"本周新增 {opened}、下架 {closed}。", ""]
    if first_ts and first_ts > since:
        out += [f"> 注：数据从 {first_ts[:10]} 开始积累，本周\"新增\"包含首次收录的存量岗位，不代表本周新发布。", ""]

    out += ["## 新增最多的公司", "", "| 公司 | 新增 | 其中校招 |", "|---|---|---|"]
    for name, n, c in rows("""SELECT c.name, COUNT(*), SUM(j.recruit_type='campus') FROM job_event e
                              JOIN job j ON j.id=e.job_id JOIN company c ON c.id=j.company_id
                              WHERE e.type='open' AND e.ts>=? AND e.ts<? GROUP BY 1 ORDER BY 2 DESC LIMIT 10""",
                           since, until):
        out.append(f"| {name} | {n} | {c} |")

    out += ["", "## 新增最多的职类", "", "| 职类 | 新增 |", "|---|---|"]
    for cat, sub, n in rows("""SELECT COALESCE(j.category,'未分类'), COALESCE(j.subcategory,''), COUNT(*)
                               FROM job_event e JOIN job j ON j.id=e.job_id
                               WHERE e.type='open' AND e.ts>=? AND e.ts<? GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10""",
                            since, until):
        out.append(f"| {cat}{' / ' + sub if sub and sub != cat else ''} | {n} |")

    out += ["", "## 2027 届校招在招岗位最多的公司", "", "| 公司 | 岗位数 |", "|---|---|"]
    for name, n in rows("""SELECT c.name, COUNT(*) FROM job j JOIN company c ON c.id=j.company_id
                           WHERE j.closed_at IS NULL AND j.recruit_type='campus' AND j.grad_year=2027
                           GROUP BY 1 ORDER BY 2 DESC LIMIT 10"""):
        out.append(f"| {name} | {n} |")
    if cal_conn is not None:
        out += link_section(cal_conn)
    out += ["", "---", "数据来自各公司官方招聘页，由 [job_radar](https://github.com/lijiaqimun-coder/job_radar) 每日自动更新。"
            "届别仅统计标题中写明届别的岗位。"]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--until", default=now_ts())
    ap.add_argument("--calendar", help="calendar.db 路径：附上投递链接探活结果")
    args = ap.parse_args()
    cal_conn = None
    if args.calendar and Path(args.calendar).exists():
        cal_conn = sqlite3.connect(args.calendar)
        cal_conn.row_factory = sqlite3.Row
    print(build(sqlite3.connect(args.db), args.until, cal_conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
