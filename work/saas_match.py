"""把云就业宣讲会条目里的公司名对齐到目标池，看能补多少家。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

SRC = ROOT / "work" / "saas_careers.jsonl"


def main() -> int:
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    covered = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, covered)
    names = [n for n, _ in target_names(targets)]
    uncovered = [n for n in names if not matched.get(n)]

    rows = []
    for line in SRC.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    comps = Counter(r["company"] for r in rows if r.get("company"))
    hit = match_targets(targets, set(comps))
    new_hit = [n for n in uncovered if hit.get(n)]
    print(f"items={len(rows)} hosts={len({r['school_host'] for r in rows})} companies={len(comps)}")
    print(f"uncovered_targets={len(uncovered)} newly={len(new_hit)}")
    out = [f"items={len(rows)} companies={len(comps)} uncovered={len(uncovered)} newly={len(new_hit)}", ""]
    for n in sorted(new_hit):
        ents = hit[n]
        cnt = sum(comps[e] for e in ents if e in comps)
        schools = sorted({r["school_host"] for r in rows if r["company"] in ents})
        out.append(f"{n}\t{ents}\t{cnt}\t{','.join(schools[:4])}")
    (ROOT / "work" / "_saas_match.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("wrote work/_saas_match.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
