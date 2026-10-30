"""云就业职位条目 -> 目标池对齐 + 每目标选最优学校站。"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

SRC = ROOT / "work" / "saas_jobs.jsonl"
OUT = ROOT / "work" / "_saas_jobs_match.txt"


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

    per_host: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.get("company"):
            per_host[r["company"]][r["school_host"]] += 1

    lines = [
        f"jobs={len(rows)} hosts={len({r['school_host'] for r in rows})} companies={len(comps)}",
        f"uncovered={len(uncovered)} newly={len(new_hit)}",
        "",
        "target\tentities\thost\tcount",
    ]
    for n in sorted(new_hit):
        ents = hit[n]
        host_count: Counter = Counter()
        total = 0
        for e in ents:
            for host, c in per_host.get(e, {}).items():
                host_count[host] += c
                total += c
        best = host_count.most_common(1)[0][0] if host_count else ""
        lines.append(f"{n}\t{ents}\t{best}\t{total}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[0])
    print(lines[1])
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
