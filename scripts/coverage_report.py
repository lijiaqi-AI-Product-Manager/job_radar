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

from jobradar.sources import load_sources  # noqa: E402


def load_targets(path: Path = ROOT / "targets" / "top_companies.yaml") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _matches(name: str, company: str) -> bool:
    return len(name) >= 2 and len(company) >= 2 and (name in company or company in name)


def match(targets: dict, companies: set[str]) -> dict[str, list[str]]:
    """目标公司 -> 匹配到的数据源公司名（空列表 = 未覆盖）。"""
    aliases = targets.get("aliases") or {}
    out = {}
    for names in targets["sectors"].values():
        for t in names:
            keys = [t, *aliases.get(t, [])]
            out[t] = sorted(c for c in companies if any(_matches(k, c) for k in keys))
    return out


def render(targets: dict, matched: dict[str, list[str]], jobs: dict[str, int] | None = None) -> str:
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
    lines += ["", "## 已覆盖", ""]
    for sector, names in targets["sectors"].items():
        got = [n for n in names if matched[n] and n not in blocked]
        if got:
            def fmt(n):
                cnt = sum((jobs or {}).get(c, 0) for c in matched[n])
                return f"{n}（{cnt}）" if jobs else n
            lines.append(f"- **{sector}**：" + "、".join(fmt(n) for n in got))
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
    args = ap.parse_args()
    targets = load_targets()
    companies = {s.company for s in load_sources(ROOT / "sources")}
    jobs = None
    if args.db:
        conn = sqlite3.connect(args.db)
        jobs = dict(conn.execute("SELECT c.name, COUNT(*) FROM job j JOIN company c ON c.id=j.company_id "
                                 "WHERE j.closed_at IS NULL GROUP BY 1"))
    print(render(targets, match(targets, companies), jobs), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
