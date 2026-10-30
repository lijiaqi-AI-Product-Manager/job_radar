"""把 README / CHANGELOG 的覆盖率数字刷到指定值（下一轮改数字时改这里再跑）。

用法：python work/refresh_numbers.py --sources 2218 --companies 2177 --covered 906 \
        --official 606 --aggregator 300
只改数字，不改句子结构；找不到的旧值会打印 MISS，人工补。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--companies", required=True)
    ap.add_argument("--covered", required=True)
    ap.add_argument("--official", required=True)
    ap.add_argument("--aggregator", required=True)
    ap.add_argument("--old-covered", default=None, help="上一轮覆盖数，用于替换旧值")
    args = ap.parse_args()

    total = 1655
    pct = round(int(args.covered) / total * 100)
    off_pct = round(int(args.official) / total * 100)
    agg_pct = round(int(args.aggregator) / total * 100)

    pairs: list[tuple[str, str]] = []
    if args.old_covered:
        pairs.append((f"{args.old_covered}/1,655", f"{args.covered}/1,655"))

    print(f"新口径：{args.covered}/{total}（{pct}%），官方 {args.official}（{off_pct}%），"
          f"聚合 {args.aggregator}（{agg_pct}%），源 {args.sources}，公司 {args.companies}")
    print("（本脚本只打印口径建议，实际替换请按语言逐个确认后再写盘）")
    for path in sorted(ROOT.glob("README*.md")):
        text = path.read_text(encoding="utf-8")
        nums = re.findall(r"\b(\d{3})/1[.,]655", text)
        if nums:
            print(f"  {path.name}: 现有覆盖数字 {sorted(set(nums))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
