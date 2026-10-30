"""盘点 work/ 下已验证候选里，还有多少没进 sources/（可直接入库的增量）。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.sources import load_sources  # noqa: E402

ADAPTER = {"beisen": "beisen", "beisen_legacy": "beisen_legacy", "hotjob": "hotjob",
           "feishu_atsx": "feishu_atsx", "feishu": "feishu_atsx", "workday": "workday",
           "beisen_host": "beisen", "tupu360": "tupu360"}


def main() -> None:
    existing = load_sources(ROOT / "sources")
    have_tenant = set()
    have_company = {s.company for s in existing}
    for s in existing:
        p = s.params or {}
        for key in ("tenant", "slug", "host"):
            v = p.get(key)
            if v:
                have_tenant.add((s.adapter, str(v).lower()))
        have_tenant.add((s.adapter, s.id.lower()))

    def seen(kind: str, slug: str) -> bool:
        a = ADAPTER.get(kind)
        if not a:
            return False
        s = str(slug).lower()
        return (a, s) in have_tenant

    cands: dict[str, dict] = {}
    sources_files = [
        ("work/verified_new_sources.jsonl", "kind", "slug", "company", "count", "title"),
        ("work/search_verified_clean.jsonl", "kind", "slug", "company", "count", "title"),
        ("work/careers_verified.jsonl", "kind", "slug", "company", "count", "title"),
        ("work/ats_verified.jsonl", "ats", "tenant", "company", "count", "title"),
    ]
    for fname, kk, sk, ck, nk, tk in sources_files:
        p = ROOT / fname
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            kind, slug, company = r.get(kk), r.get(sk), r.get(ck)
            if not kind or not slug or not company:
                continue
            if seen(kind, slug):
                continue
            key = f"{kind}:{str(slug).lower()}"
            if key in cands:
                continue
            cands[key] = {"kind": kind, "slug": slug, "company": company,
                          "count": r.get(nk), "title": r.get(tk), "src": fname}

    fresh = [c for c in cands.values() if c["company"] not in have_company]
    same_company = [c for c in cands.values() if c["company"] in have_company]
    out = [f"未入库候选 {len(cands)}：公司是新的 {len(fresh)}，公司已有源(重复) {len(same_company)}", ""]
    out.append("## 公司尚未入库的候选")
    for c in sorted(fresh, key=lambda x: -(int(x["count"]) if str(x["count"]).lstrip("-").isdigit() else 0)):
        out.append(f"{c['company']}\t{c['kind']}\t{c['slug']}\tcount={c['count']}\t{c['title']}\t{c['src']}")
    out.append("")
    out.append("## 公司已有源但租户不同（可能是另一门户，需人工判重）")
    for c in same_company[:80]:
        out.append(f"{c['company']}\t{c['kind']}\t{c['slug']}\tcount={c['count']}\t{c['src']}")
    (ROOT / "work" / "_intake_backlog.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"candidates={len(cands)} fresh={len(fresh)} dup_company={len(same_company)}")


if __name__ == "__main__":
    main()
