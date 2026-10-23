"""日历字段完整度报告：每条条目该有的字段填了多少。

需求（2026-10-23 用户明确）：日历条目必须包含
  集团 / 具体公司或产品 / 届次 / 项目类型 / 方向（track 级，最好带岗位名）/
  网申时间 / 城市 / 投递入口 / 来源（含日期）/ 数据时间戳；有公开 JD 就挂上，
  被验证码/登录墙挡住则只发日历并在末尾加「{公司}希望你去他们的招聘页逛一逛哦~」。

用法：
    uv run python scripts/calendar_field_report.py ~/.jobradar/calendar.db [--top 20]
"""

import argparse
import sqlite3
import sys
from collections import Counter

REQUIRED = {
    "group_name": "集团",
    "company": "具体公司/产品",
    "grad_year": "届次",
    "project_type": "项目类型",
    "tracks": "方向",
    "apply_start": "网申开始",
    "apply_end": "网申截止",
    "cities": "城市",
    "apply_url": "投递入口",
    "source_name": "来源",
    "as_of": "数据时间戳",
}


def filled(row, key) -> bool:
    v = row[key]
    if v is None:
        return False
    if isinstance(v, str) and v.strip() in ("", "[]", "null"):
        return False
    if isinstance(v, (list, dict)) and not v:
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--top", type=int, default=10, help="每组列出多少条缺字段的条目")
    args = ap.parse_args()
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM entry").fetchall()
    for origin in ("manual", "auto"):
        sub = [r for r in rows if r["origin"] == origin]
        if not sub:
            continue
        print(f"\n=== {origin}（{len(sub)} 条）===")
        for key, label in REQUIRED.items():
            n = sum(1 for r in sub if filled(r, key))
            print(f"  {label:10s} {key:14s} {n:>4}/{len(sub)} = {n / len(sub):5.1%}")
        missing = Counter()
        for r in sub:
            for key in REQUIRED:
                if not filled(r, key):
                    missing[key] += 1
        print("  缺得最多的字段:", [f"{k}({v})" for k, v in missing.most_common(4)])

    # 没有数据源、只有日历的公司：它们的条目完整度
    con2 = sqlite3.connect(args.db)
    con2.row_factory = sqlite3.Row
    only_cal = {r["name"] for r in con2.execute(
        "SELECT name FROM target WHERE data_companies IS NULL OR data_companies IN ('','[]')")}
    sub = [r for r in rows if r["group_name"] in only_cal]
    print(f"\n=== 只有日历（无数据源）的公司条目 {len(sub)} 条 ===")
    for key, label in REQUIRED.items():
        n = sum(1 for r in sub if filled(r, key))
        print(f"  {label:10s} {n:>4}/{len(sub)} = {n / len(sub):5.1%}")

    # 典型样本
    print("\n=== 缺的最多的样本 ===")
    scored = []
    for r in rows:
        miss = [k for k in REQUIRED if not filled(r, k)]
        scored.append((len(miss), r, miss))
    scored.sort(key=lambda x: -x[0])
    for n, r, miss in scored[: args.top]:
        print(f"  [{r['origin']}] {r['group_name']} / {r['company']} | 缺 {n}: {','.join(miss)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
