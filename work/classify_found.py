"""把 `verify_found.py` 的验证结果分类：已收录 / 名称不符待核 / 门户空。

为什么需要：验证脚本只回答「这个门户活着吗、名字对得上吗」，但要不要**收进 sources**
还得看两件事——① 是不是已经收过（同租户、同公司换了个 slug）；② 名字核对失败的到底是
「门户标题没写公司名」还是「根本是别家公司的门户」。

第 ② 条是这一轮踩过的坑：`ys.zhiye.com` 标题是「多品牌门户」，里面十几个互不相关的公司；
`baicgroup` 挂在「奔驰」名下但其实是北汽集团。所以这里**不自动采信**，只把 `??`（门户有岗
但名字没对上）单独列出来，由人工打开门户确认后再写 YAML。

用法：
    python3 work/classify_found.py --in /tmp/exp/ver5.jsonl [--apply]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sources"


def load_existing() -> tuple[set[str], set[str], set[str]]:
    tenants: set[str] = set()
    slugs: set[str] = set()
    companies: set[str] = set()
    for f in SRC.glob("*.yaml"):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        for s in d.get("sources") or []:
            if not isinstance(s, dict):
                continue
            p = s.get("params") or {}
            if p.get("tenant"):
                tenants.add(str(p["tenant"]).lower())
            if p.get("slug"):
                slugs.add(str(p["slug"]).lower())
            if s.get("company"):
                companies.add(str(s["company"]))
    return tenants, slugs, companies


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="/tmp/exp/ver5.jsonl")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    tenants, slugs, companies = load_existing()
    recs = [json.loads(ln) for ln in Path(a.src).read_text(encoding="utf-8").splitlines() if ln.strip()]

    new_ok, dup, unsure, empty = [], [], [], []
    for r in recs:
        key = r.get("slug") or r.get("tenant") or ""
        alive = r.get("ok") and r.get("count", 0) > 0
        if not alive:
            empty.append(r)
            continue
        if key.lower() in tenants or key.lower() in slugs or r.get("company") in companies:
            dup.append(r)
        elif r.get("name_hit"):
            new_ok.append(r)
        else:
            unsure.append(r)

    print(f"总计 {len(recs)}：新增可用 {len(new_ok)} / 已收录 {len(dup)} / 待核 {len(unsure)} / 空门户 {len(empty)}")
    print("\n=== 新增可用 ===")
    for r in new_ok:
        print(f"  {r.get('slug') or r.get('tenant'):32s} {r['count']:6d}  {r.get('title','')[:30]:30s} "
              f"{(r.get('jobs') or [''])[0][:26]}  company={r.get('company')}")
    print("\n=== 待人工确认（门户有岗但标题对不上）===")
    for r in unsure:
        print(f"  {r.get('slug') or r.get('tenant'):32s} {r['count']:6d}  {r.get('title','')[:30]:30s} "
              f"{(r.get('jobs') or [''])[0][:26]}  company={r.get('company')}")
    print("\n=== 空门户（不收录）===")
    print("  " + "、".join(str(r.get("slug") or r.get("tenant")) for r in empty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
