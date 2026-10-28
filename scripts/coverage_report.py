"""对照覆盖目标（targets/top_companies.yaml）与已接入的数据源，输出覆盖率报告（Markdown）。

用法：python scripts/coverage_report.py [--db data/jobs.db] > coverage.md
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def load_targets(path: Path = ROOT / "targets" / "top_companies.yaml") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_industries(path: Path = ROOT / "targets" / "industries.yaml") -> dict:
    """365 行细分行业 → 每行 2-4 家代表企业；文件不存在时返回空。"""
    return yaml.safe_load(path.read_text(encoding="utf-8"))["sectors"] if path.exists() else {}


def match(targets: dict, companies: set[str]) -> dict[str, list[str]]:
    """与日历共用同一套匹配（精确匹配优先，别名生效），避免两处规则漂移。"""
    return match_targets(targets, companies)


def render(targets: dict, matched: dict[str, list[str]], jobs: dict[str, int] | None = None,
           companies: set[str] | None = None) -> str:
    blocked = targets.get("blocked") or {}
    total = len(matched)
    # blocked 的公司即使被子串误匹配（「京东」in「京东方」）也不能算已覆盖
    covered = sum(1 for k, v in matched.items() if v and k not in blocked)
    lines = ["# 覆盖率报告", "",
             f"目标 {total} 家：已覆盖 **{covered}**（{covered / total:.0%}），"
             f"不可合规覆盖 {len(blocked)}，待侦察 {total - covered - len(blocked)}。", "",
             "| 行业 | 目标 | 已覆盖 | 覆盖率 |", "|---|---|---|---|"]
    for sector, names in targets["sectors"].items():
        c = sum(1 for n in names if matched[n] and n not in blocked)
        lines.append(f"| {sector} | {len(names)} | {c} | {c / len(names):.0%} |")
    prov = targets.get("provinces") or {}
    if prov:
        lines += ["", f"## 分省覆盖率（{len(prov)} 个省级行政区）", "",
                  "| 省份 | 目标 | 已覆盖 | 覆盖率 |", "|---|---|---|---|"]
        empty = []
        for p, names in prov.items():
            uniq = list(dict.fromkeys(names))
            c = sum(1 for n in uniq if matched.get(n) and n not in blocked)
            lines.append(f"| {p} | {len(uniq)} | {c} | {c / len(uniq):.0%} |")
            if c == 0:
                empty.append(p)
        if empty:
            lines.append(f"\n零覆盖省份 {len(empty)} 个：{'、'.join(empty)}")
    lines += ["", "## 已覆盖", ""]
    for sector, names in targets["sectors"].items():
        got = [n for n in names if matched[n] and n not in blocked]
        if got:
            def fmt(n):
                cnt = sum((jobs or {}).get(c, 0) for c in matched[n])
                return f"{n}（{cnt}）" if jobs else n
            lines.append(f"- **{sector}**：" + "、".join(fmt(n) for n in got))
    ind = load_industries()
    comp = companies or set()
    if ind:
        lines += ["", "## 细分行业覆盖（365 行）", "", "| 板块 | 行数 | 有覆盖 | 覆盖率 |", "|---|---|---|---|"]
        hit_rows = miss_rows = 0
        for sec, rows in ind.items():
            hit = 0
            for _line, names in rows.items():
                if any(match_targets({"sectors": {"x": [str(n)]}}, comp).get(str(n)) for n in names):
                    hit += 1
            hit_rows += hit
            miss_rows += len(rows) - hit
            lines.append(f"| {sec} | {len(rows)} | {hit} | {hit / len(rows):.0%} |")
        lines.append(f"\n合计 {hit_rows + miss_rows} 行：有覆盖 **{hit_rows}**（{hit_rows / (hit_rows + miss_rows):.0%}），"
                     f"零覆盖 {miss_rows}。")
    lines += ["", "## 不可合规覆盖", ""] + [f"- {n}：{r}" for n, r in blocked.items()]
    lines += ["", "## 待侦察", ""]
    for sector, names in targets["sectors"].items():
        todo = [n for n in names if not matched[n] and n not in blocked]
        if todo:
            lines.append(f"- **{sector}**：" + "、".join(todo))
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="jobs.db 路径；给出时显示每家在招岗位数")
    ap.add_argument("--json", action="store_true", help="只输出摘要 JSON（给脚本/看板用）")
    args = ap.parse_args()
    targets = load_targets()
    companies = {s.company for s in load_sources(ROOT / "sources")}
    jobs = None
    if args.db:
        conn = sqlite3.connect(args.db)
        jobs = dict(conn.execute("SELECT c.name, COUNT(*) FROM job j JOIN company c ON c.id=j.company_id "
                                 "WHERE j.closed_at IS NULL GROUP BY 1"))
    matched = match(targets, companies)
    if args.json:
        import json
        blocked = targets.get("blocked") or {}
        total = len(matched)
        covered = sum(1 for k, v in matched.items() if v and k not in blocked)
        ind = load_industries()
        rows = hit = 0
        comp = companies
        for _sec, lines_ in ind.items():
            for _line, names in lines_.items():
                rows += 1
                if any(match_targets({"sectors": {"x": [str(n)]}}, comp).get(str(n)) for n in names):
                    hit += 1
        print(json.dumps({"targets": total, "covered": covered, "blocked": len(blocked),
                          "sources": len({s.id for s in load_sources(ROOT / "sources")}),
                          "companies": len(companies), "industry_rows": rows,
                          "industry_covered": hit}, ensure_ascii=False))
        return 0
    print(render(targets, matched, jobs, companies), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
