"""按省份统计「全国知名 + 省内知名」企业的源覆盖，出各省明细。

用户要的是「先补全国知名到 1500，再补各省各地知名」，所以覆盖率必须**能按省看**：
只报一个总数，看不出河北 3/26、西藏 0/0 这种结构性短板。

口径（与 coverage_lib 一致，不另立标准）：
  covered = targets 里所有 sector 的公司 ∪ sources/*.yaml 里的公司 ∪ 库里有岗位的公司
  by_province 里同名的只算一次；某公司同时属于全国名单和省份名单时两边都计。

用法：
    python3 work/province_report.py                # 只看
    python3 work/province_report.py --json out.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))

from coverage_lib import coverage  # noqa: E402

MEGA = ROOT / "targets/mega_companies.yaml"


def main() -> int:
    coverage("/tmp/fc2/jobs.db")  # 只为打印分板块报表；覆盖集合下面另算（全库源 + 库内公司并集）
    # coverage() 只统计 top_companies.yaml 的 sectors；这里换成「全库源 + 库内公司」的并集。
    from coverage_lib import db_companies, source_companies
    sc = source_companies()
    db = db_companies("/tmp/fc2/jobs.db")
    covered = set(sc) | set(db)
    d = yaml.safe_load(MEGA.read_text(encoding="utf-8")) or {}
    national = [str(x) for x in (d.get("national") or [])]
    bp = {str(k): [str(x) for x in v] for k, v in (d.get("by_province") or {}).items()}

    nat_hit = [n for n in national if n in covered]
    rows = []
    for prov, names in bp.items():
        uniq = list(dict.fromkeys(names))
        hit = [n for n in uniq if n in covered]
        rows.append({"province": prov, "total": len(uniq), "covered": len(hit),
                     "pct": round(100 * len(hit) / len(uniq), 1) if uniq else 0.0,
                     "missing": [n for n in uniq if n not in covered]})
    rows.sort(key=lambda x: (-x["covered"] / x["total"] if x["total"] else 0, -x["total"]))

    allprov = {n for v in bp.values() for n in v}
    prov_hit = len(allprov & covered)
    print(json.dumps({
        "covered_total": len(covered),
        "national": {"total": len(national), "covered": len(nat_hit)},
        "by_province": {"total": len(allprov), "covered": prov_hit},
        "provinces": len(bp),
    }, ensure_ascii=False, indent=2))
    print(f"{'省':6s} {'覆盖':>7s} {'占比':>6s}  缺口前 5")
    for x in rows:
        print(f"{x['province']:6s} {x['covered']:3d}/{x['total']:<3d} {x['pct']:5.1f}%  "
              + "、".join(x["missing"][:5]))
    if len(sys.argv) > 2 and sys.argv[1] == "--json":
        Path(sys.argv[2]).write_text(json.dumps({"national_hit": nat_hit,
                                                 "provinces": rows}, ensure_ascii=False,
                                                indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
