"""各省「可做公司」覆盖率报告：按省列出 target / covered / 缺口，并给出缺口明细。

为什么单独成脚本：`targets/mega_companies.yaml` 的 `by_province` 现在和 `national`
完全重叠（802 家全部也在 national 里），所以「省级覆盖」看着 0 进展其实是口径问题。
这份报告按**省份**切片，把「这家公司属于哪些省」摊开看，才知道下一批该往哪投。

用法：
    python3 work/prov_report2.py                       # 打印
    python3 work/prov_report2.py --json /tmp/p.json    # 落盘
    python3 work/prov_report2.py --top 8               # 每省列前 8 家缺口公司
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))

from coverage_lib import coverage  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/fc2/jobs.db")
    ap.add_argument("--json", dest="js", default="")
    ap.add_argument("--top", type=int, default=6)
    a = ap.parse_args()
    cov = coverage(a.db)
    covered = set()
    # coverage() 只返回计数和 missing，这里重算一次「已覆盖」集合
    from coverage_lib import db_companies, source_companies
    covered = set(source_companies()) | db_companies(a.db)

    tgt = yaml.safe_load((ROOT / "targets/mega_companies.yaml").read_text(encoding="utf-8")) or {}
    nat = set(tgt.get("national") or [])
    rows = []
    for prov, names in (tgt.get("by_province") or {}).items():
        s = set(names)
        rows.append({"province": prov, "total": len(s), "covered": len(s & covered),
                     "missing": sorted(s - covered)})
    rows.sort(key=lambda r: (r["covered"] / max(1, r["total"]), -r["total"]))

    print(f"全国名单 {len(nat)} 家，已覆盖 {len(nat & covered)}；"
          f"省份切片 {len(rows)} 个，合计 {sum(r['total'] for r in rows)} 家")
    print(f"{'省份':6s} {'覆盖':>10s}  缺口样例")
    for r in rows:
        pct = r["covered"] / max(1, r["total"]) * 100
        print(f"{r['province']:6s} {r['covered']:3d}/{r['total']:3d} {pct:5.1f}%  "
              f"{'、'.join(r['missing'][:a.top])}")
    if a.js:
        Path(a.js).write_text(json.dumps({"summary": {k: v for k, v in cov.items() if k != "missing"},
                                          "provinces": rows}, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        print(f"已写 {a.js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
