"""把「名称核对通过」的北森租户写成 sources/beisen.yaml 条目（带证据注释、强制查重）。

为什么单独一步：`beisen_par.py` 的命中里有一批是**拼音撞车**（`hm` 命中 H&M 门店、
`tongwei` 命中「同为股份」的储能岗、`shzp` 命中劳务派遣公司）。直接入库会把覆盖率
做虚。所以这里把「门户页面标题 / 岗位名样本」拿给**人核**（就是我），只写入核过的。

用法：`python3 work/write_beisen_sources.py --in acc.json --apply`
acc.json 每项：{id, company, tenant, count, note, max_pages?}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TODAY = "2026-10-27"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    items = json.loads(Path(a.src).read_text(encoding="utf-8"))

    p = ROOT / "sources/beisen.yaml"
    txt = p.read_text(encoding="utf-8")
    d = yaml.safe_load(txt) or {}
    ids = {s["id"] for s in (d.get("sources") or [])}
    tens = {(s.get("params") or {}).get("tenant") for s in (d.get("sources") or [])}
    lines = []
    for r in items:
        if r["id"] in ids or r["tenant"] in tens:
            print(f"跳过重复 {r['id']} / {r['tenant']}")
            continue
        ids.add(r["id"])
        tens.add(r["tenant"])
        mp = f", max_pages: {r['max_pages']}" if r.get("max_pages") else ""
        line = (f"  - {{id: {r['id']}, company: {r['company']}, "
                f"params: {{tenant: {r['tenant']}{mp}}}}}"
                f"  # {TODAY} 租户穷举：{r['count']} 岗；{r['note']}\n")
        lines.append(line)
    print(f"新增 {len(lines)} 条")
    for ln in lines:
        print(ln.rstrip()[:200])
    if a.apply and lines:
        if not txt.endswith("\n"):
            txt += "\n"
        p.write_text(txt + "".join(lines), encoding="utf-8")
        print(f"写入 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
