"""365 行细分行业覆盖：每行至少有一家代表企业已接入，才算「这行有覆盖」。

数据源 = targets/industries.yaml（23 个板块 / 365 行 / 每行 2-4 家代表企业）。
判定口径与覆盖率报表一致：取 sources/ 里所有 source.company，走
calendar.match_targets 的精确+别名+子串规则（同一套，避免两处漂移）。

用法：
    python work/industry_coverage.py            # 打印汇总 + 每板块表
    python work/industry_coverage.py --details  # 另外列出零覆盖的行
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobradar.pipeline.calendar import match_targets  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

INDUSTRIES = ROOT / "targets" / "industries.yaml"
TARGETS = ROOT / "targets" / "top_companies.yaml"


def load() -> tuple[dict, dict, dict]:
    ind = yaml.safe_load(INDUSTRIES.read_text(encoding="utf-8"))["sectors"]
    tgt = yaml.safe_load(TARGETS.read_text(encoding="utf-8"))
    return ind, tgt, {s.company for s in load_sources("sources")}


def compute(ind: dict, tgt: dict, companies: set[str]) -> dict[str, dict]:
    """每个板块 -> {总行数, 有覆盖行数, 零覆盖行列表}。"""
    aliases = tgt.get("aliases") or {}
    blocked = set(tgt.get("blocked") or [])
    # 逐行独立匹配：match_targets 的键是「公司名」而不是板块名，所以按公司名回查
    out: dict[str, dict] = {}
    for sec, rows in ind.items():
        hit, miss = [], []
        for line, names in rows.items():
            got = []
            for n in names:
                n = str(n)
                if n in blocked:
                    continue
                m = match_targets({"sectors": {"x": [n]}, "aliases": aliases}, companies).get(n) or []
                if m:
                    got.append(n)
            (hit if got else miss).append(line if not got else f"{line}（{got[0]}）")
        out[sec] = {"total": len(rows), "hit": len(hit), "rows": hit, "miss": miss}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--details", action="store_true")
    a = ap.parse_args(argv)
    ind, tgt, companies = load()
    res = compute(ind, tgt, companies)
    total = sum(r["total"] for r in res.values())
    hit = sum(r["hit"] for r in res.values())
    print(f"细分行业 {total} 行：有覆盖 {hit}（{hit / total:.0%}），零覆盖 {total - hit}")
    print("| 板块 | 行数 | 有覆盖 | 覆盖率 |")
    print("|---|---|---|---|")
    for sec, r in res.items():
        print(f"| {sec} | {r['total']} | {r['hit']} | {r['hit'] / r['total']:.0%} |")
    if a.details:
        print("\n零覆盖的行：")
        for sec, r in res.items():
            if r["miss"]:
                print(f"- {sec}：{'、'.join(r['miss'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
