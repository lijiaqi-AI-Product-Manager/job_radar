"""把「实测已可抓、但还没进 sources/」的公司真正加成数据源。

为什么要有这一步：`work/sample_stats_all.jsonl` 里 122 家租户是**真的打通过列表接口**的
（normalized>0），但 `sources/` 里只有 272 家公司。这个落差意味着：
侦察报告说「可做 122 家」，产品实际只能抓 28 家——数据源覆盖这道闸门永远过不了。

本脚本只做一件事：把差集（已实测可抓 ∧ 不在 sources/ ∧ 不在 blocked）写进
`sources/beisen.yaml` / `sources/hotjob.yaml` / `sources/beisen_legacy.yaml`，
并把租户去重做对（同一 tenant 已有源则不重复添加）。

红线：
  - 只加**实测通过**的（normalized>0 且 jd_rate≥0.9），不猜、不试探。
  - targets 里的 blocked 名单、ATS 厂商自身域名一律排除。
  - 不修改任何已有条目，只追加。
"""

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"

# ATS 厂商自己不是雇主，抓他们没意义（这类条目在候选池里混进来过）
VENDORS = {"moka", "北森", "大易", "hotjob", "beisen", "mokahr", "dayee", "zhiye"}


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def slug_tenant(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:30]


def main() -> int:
    apply = "--apply" in sys.argv
    stats = load_jsonl(WORK / "sample_stats_all.jsonl")
    doable = [r for r in stats if r.get("normalized", 0) > 0 and r.get("jd_rate", 0) >= 0.9]

    tgt = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8")) or {}
    blocked = set((tgt.get("blocked") or {}).keys())
    in_targets: set[str] = set()
    for names in (tgt.get("sectors") or {}).values():
        in_targets |= set(names or [])

    # 现有源：按 (adapter, tenant) 去重，比按公司名去重更严格——
    # 同一家公司可能挂了两个租户（如 changan / changanqiche），都是真源，不能互相顶掉。
    files = {"beisen": "sources/beisen.yaml",
             "beisen_legacy": "sources/beisen_legacy.yaml",
             "hotjob": "sources/hotjob.yaml"}
    seen: set[tuple[str, str]] = set()
    used_ids: set[str] = set()
    doc_by_adapter: dict[str, dict] = {}
    for adapter, rel in files.items():
        p = ROOT / rel
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        doc_by_adapter[adapter] = {"path": p, "doc": doc, "raw": p.read_text(encoding="utf-8")}
        for s in doc.get("sources") or []:
            used_ids.add(s["id"])
            ad = s.get("adapter") or (doc.get("defaults") or {}).get("adapter") or adapter
            ten = str((s.get("params") or {}).get("tenant") or "")
            if ten:
                seen.add((ad, ten))

    added: dict[str, list[dict]] = {k: [] for k in files}
    skipped: list[tuple[str, str]] = []
    for r in sorted(doable, key=lambda x: -(x.get("count") or 0)):
        name, ats, tenant = r["name"], r["ats"], str(r["tenant"])
        if ats not in files:
            skipped.append((name, f"adapter {ats} 未接入"))
            continue
        if name in blocked:
            skipped.append((name, "in_blocked_list"))
            continue
        if re.sub(r"[^a-z]", "", name.lower()) in VENDORS:
            skipped.append((name, "ats_vendor"))
            continue
        if (ats, tenant) in seen:
            skipped.append((name, "already_in_sources"))
            continue
        sid = f"{ats.replace('_', '-')}-{slug_tenant(tenant)}"
        n = 2
        base = sid
        while sid in used_ids:
            sid = f"{base}-{n}"
            n += 1
        used_ids.add(sid)
        params = {"tenant": tenant}
        if ats == "hotjob":
            params = {"host": r["host"], "tenant": tenant}
        elif ats == "beisen_legacy":
            params = {"tenant": tenant, "portal": "campus"}
        rec = {"id": sid, "company": name, "params": params,
               "_note": f"{r.get('normalized')} 岗实测（{r.get('title', '')[:20]}）"}
        added[ats].append(rec)
        seen.add((ats, tenant))

    total = sum(len(v) for v in added.values())
    print(f"可加入 {total} 家；跳过 {len(skipped)} 家")
    for k, v in added.items():
        if v:
            print(f"  {k}: {len(v)}")
    for c, why in skipped[:20]:
        print(f"  - {c}: {why}")
    if not apply:
        print("（dry-run，加 --apply 才写文件）")
        return 0

    for ats, recs in added.items():
        if not recs:
            continue
        p = doc_by_adapter[ats]["path"]
        raw = doc_by_adapter[ats]["raw"].rstrip("\n")
        lines = []
        for rec in recs:
            params = ", ".join(f"{k}: {v}" for k, v in rec["params"].items())
            lines.append(f"  - id: {rec['id']}\n"
                         f"    company: {rec['company']}\n"
                         f"    params: {{{params}}}  # {rec['_note']}\n")
        p.write_text(raw + "\n" + "".join(lines), encoding="utf-8")
        print(f"写入 {p.relative_to(ROOT)}：+{len(recs)}")

    # 立刻回读校验：YAML 必须还能解析，且条目数只增不减
    for _ats, rel in files.items():
        doc = yaml.safe_load((ROOT / rel).read_text(encoding="utf-8")) or {}
        print(f"  复核 {rel}: {len(doc.get('sources') or [])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
