"""把 tupu_scan.py 的扫描结果转成 sources/tupu360.yaml 条目（人工复核后再落盘）。

用法：python3 work/tupu_add.py --in /tmp/exp/tupu_scan.json
只打印建议条目，不写文件 —— 归属必须人工核对 title，脚本不替人做判断。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MIN_JOBS = 5  # 少于 5 岗的租户不值得占一个源配置（多为试用环境 / 演示站）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="/tmp/exp/tupu_scan.json")
    ap.add_argument("--min", type=int, default=MIN_JOBS)
    a = ap.parse_args()
    rows = json.loads(Path(a.src).read_text(encoding="utf-8"))
    keep = [r for r in rows if (r["campus"] or 0) + (r["social"] or 0) >= a.min]
    keep.sort(key=lambda r: -((r["campus"] or 0) + (r["social"] or 0)))
    print(f"总租户 {len(rows)}，≥{a.min} 岗 {len(keep)}")
    print(f"{'campus':>6} {'social':>6}  tenant")
    for r in keep:
        print(f"{r['campus']!s:>6} {r['social']!s:>6}  {r['tenant']:24s} {r['name'][:30]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
