"""列出各省未覆盖目标，供定向拓源使用。

输出：work/province_gap.json —— 每省未覆盖公司名单 + 是否已在 companies.jsonl。
用法：python work/province_gap.py [--province 海南] [--limit 40]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))

import yaml  # noqa: E402
from verify_tenants_found import core  # noqa: E402

from jobradar.sources import load_sources  # noqa: E402


def load_targets() -> dict[str, list[str]]:
    data = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    return data.get("sectors", {}) | {f"省域·{k}": v for k, v in data.get("provinces", {}).items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--province", default="", help="只输出某个省（不带 省域· 前缀）")
    ap.add_argument("--limit", type=int, default=0, help="每省最多列多少家")
    ap.add_argument("--out", default="work/province_gap.json")
    args = ap.parse_args()

    covered = {core(s.company) for s in load_sources(ROOT / "sources")}
    known = {core(json.loads(line)["company"]) for line in (ROOT / "companies.jsonl").open(encoding="utf-8")}
    targets = load_targets()

    result: dict[str, list[dict]] = {}
    for section, names in targets.items():
        if not section.startswith("省域·"):
            continue
        prov = section.split("·", 1)[1]
        if args.province and prov != args.province:
            continue
        missing = []
        for name in names:
            if core(name) in covered:
                continue
            missing.append({"company": name, "in_companies_jsonl": core(name) in known})
            if args.limit and len(missing) >= args.limit:
                break
        result[prov] = missing

    out = ROOT / args.out
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(v) for v in result.values())
    print(f"省份 {len(result)} 个，未覆盖 {total} 家 -> {out}")
    for prov, items in sorted(result.items(), key=lambda kv: -len(kv[1]))[:10]:
        print(f"  {prov}: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
