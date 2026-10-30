"""把实习僧全量列表索引与未覆盖目标池对齐，输出「索引里出现但还没建源」的公司。

用法：python work/index_match.py  -> work/_index_match.txt
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

INDEX = ROOT / "work" / "sxs_index.jsonl"
OUT = ROOT / "work" / "_index_match.txt"

STRIP = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司)$")


def core(name: str) -> str:
    n = (name or "").strip()
    n = STRIP.sub("", n)
    return n or (name or "").strip()


def main() -> int:
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    companies = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, companies)
    names = [n for n, _ in target_names(targets)]
    uncovered = [n for n in names if not matched.get(n)]
    print(f"targets={len(names)} uncovered={len(uncovered)}")

    counter: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    rows = 0
    if INDEX.exists():
        for line in INDEX.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows += 1
            cn = r.get("cname")
            if not cn:
                continue
            counter[cn] += 1
            samples.setdefault(cn, []).append(r.get("name") or "")
    print(f"index_rows={rows} distinct_cnames={len(counter)}")

    unc_core = {core(n): n for n in uncovered}
    hits: list[tuple[str, str, int]] = []
    for cn, cnt in counter.items():
        c = core(cn)
        if not c:
            continue
        for key, target in unc_core.items():
            if not key or not c:
                continue
            if c == key or (len(key) >= 2 and len(c) >= 2 and (key.startswith(c) or c.startswith(key))):
                if min(len(key), len(c)) >= 2 and abs(len(key) - len(c)) <= 6:
                    hits.append((target, cn, cnt))
                    break

    lines = [f"index_rows={rows} distinct_cnames={len(counter)} uncovered={len(uncovered)}", ""]
    seen = set()
    for target, cn, cnt in sorted(hits, key=lambda x: -x[2]):
        if target in seen:
            continue
        seen.add(target)
        lines.append(f"{target}\t{cn}\t{cnt}\t{' | '.join(samples.get(cn, [])[:2])}")
    lines.insert(1, f"matched_targets={len(seen)}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"matched_targets={len(seen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
