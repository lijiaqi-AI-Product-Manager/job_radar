"""把已发现的子域/主机名与「还没建源的目标公司」做拼音对齐。

反过来做：拿目标公司名生成拼音候选，看它是否已经躺在已知子域集合里。
命中说明「这家公司有门户，只是当时没探到」，可以直接进验证队列。
覆盖率口径与 scripts/coverage_report.py 完全一致（复用 match_targets）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))

from beisen_tenant_sweep import candidates, load_pinyin  # noqa: E402

from jobradar.pipeline.calendar import match_targets  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def discovered(domain: str) -> set[str]:
    data = json.loads((ROOT / "work" / "sd_center.json").read_text(encoding="utf-8"))
    out = set()
    for host in data.get(domain, []):
        label = host.split(".")[0].strip().lower()
        if label and label not in {"www", "m", "api", "campus", "jobs", "static", "cdn"}:
            out.add(label)
    return out


def main() -> int:
    pinyin = load_pinyin()
    sources = load_sources(ROOT / "sources")
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    blocked = targets.get("blocked") or {}
    matched = match_targets(targets, {s.company for s in sources})

    uncovered: list[tuple[str, str]] = []
    for sector, names in targets["sectors"].items():
        uncovered += [(n, sector) for n in names if not matched[n] and n not in blocked]
    for prov, names in (targets.get("provinces") or {}).items():
        uncovered += [(n, f"省域·{prov}") for n in names if not matched[n] and n not in blocked]

    pools = {
        "beisen": discovered("zhiye.com"),
        "hotjob": discovered("hotjob.cn"),
        "feishu": discovered("jobs.feishu.cn"),
    }
    hits: list[dict] = []
    for name, origin in uncovered:
        for slug in candidates(name, pinyin):
            for kind, pool in pools.items():
                if slug in pool:
                    hits.append({"company": name, "origin": origin, "kind": kind, "slug": slug})

    order = {"beisen": 0, "hotjob": 1, "feishu": 2}
    hits.sort(key=lambda h: (order[h["kind"]], h["origin"], h["company"]))
    out = ROOT / "work" / "host_matches.jsonl"
    out.write_text(
        "".join(json.dumps(h, ensure_ascii=False) + "\n" for h in hits), encoding="utf-8"
    )
    print(f"未建源目标 {len(uncovered)} 家，命中 {len(hits)} 条 -> {out.name}")
    by_kind: dict[str, int] = {}
    for h in hits:
        by_kind[h["kind"]] = by_kind.get(h["kind"], 0) + 1
    print("分布", by_kind)
    for h in hits[:60]:
        print(f"  {h['kind']:<7} {h['slug']:<26} {h['company']}（{h['origin']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
