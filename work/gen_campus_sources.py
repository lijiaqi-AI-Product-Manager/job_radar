"""南开就业网采集结果 -> 建源候选清单（人工复核用）。

输出 work/_campus_candidates.txt：目标公司 / 就业网登记名 / 条数 / 样例标题。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

STRIP = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司)$")


def core(name: str) -> str:
    return STRIP.sub("", (name or "").strip()) or (name or "").strip()


def main() -> int:
    rows = [json.loads(ln) for ln in (ROOT / "work" / "campus_nankai.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    covered = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, covered)
    names = [n for n, _ in target_names(targets)]
    uncovered = [n for n in names if not matched.get(n)]

    by_company: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_company[r["company"]].append(r)

    hits: list[tuple[str, str, int, list[str]]] = []
    for target in uncovered:
        tc = core(target)
        if not tc:
            continue
        for cname, items in by_company.items():
            cc = core(cname)
            if not cc:
                continue
            # 严格：归一后相等，或以目标名开头且长度差 ≤ 12
            if cc == tc or (cc.startswith(tc) and len(cc) - len(tc) <= 12):
                hits.append((target, cname, len(items), [i["title"][:34] for i in items[:2]]))
    hits.sort(key=lambda x: (-x[2], x[0]))

    lines = [f"postings={len(rows)} board_companies={len(by_company)} uncovered={len(uncovered)} candidates={len(hits)}", ""]
    for target, cname, cnt, samples in hits:
        lines.append(f"{target}\t{cname}\t{cnt}\t{' | '.join(samples)}")
    (ROOT / "work" / "_campus_candidates.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    c = Counter(h[0] for h in hits)
    print(f"candidates={len(hits)} distinct_targets={len(c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
