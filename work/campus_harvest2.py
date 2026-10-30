"""多校就业网采集 + 目标匹配。

对 SCHOOLS 里每个学校翻列表页，解析后：
- 落 work/campus_<school>.jsonl（全量条目）
- 用 match_targets 对齐目标池，输出 work/_campus_match_all.txt（各校新命中）

用法：python work/campus_harvest2.py --schools tiangong,hebut,tust --pages 60
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.campus import SCHOOLS, parse_list_page  # noqa: E402
from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def harvest(client: httpx.Client, school: str, pages: int, gap: float) -> list[dict]:
    cfg = SCHOOLS[school]
    rows: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        url = cfg["list"].format(page=page) if page > 1 else cfg["list_url"]
        try:
            r = client.get(url)
        except Exception as exc:  # noqa: BLE001
            print(f"{school} page {page} error {type(exc).__name__}", flush=True)
            break
        items = parse_list_page(r.text, cfg["base"]) if r.status_code == 200 else []
        new = 0
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            it["school"] = school
            rows.append(it)
            new += 1
        print(f"{school} page {page} status={r.status_code} items={len(items)} new={new} total={len(rows)}", flush=True)
        if not items:
            break
        time.sleep(gap)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schools", default=",".join(k for k in SCHOOLS if k != "nankai"))
    ap.add_argument("--pages", type=int, default=60)
    ap.add_argument("--gap", type=float, default=0.8)
    args = ap.parse_args()

    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    covered = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, covered)
    names = [n for n, _ in target_names(targets)]
    uncovered = [n for n in names if not matched.get(n)]

    all_rows: list[dict] = []
    with httpx.Client(timeout=20.0, headers=H, follow_redirects=True, verify=False) as c:
        for school in [s.strip() for s in args.schools.split(",") if s.strip()]:
            if school not in SCHOOLS:
                raise SystemExit(f"unknown school {school}")
            rows = harvest(c, school, args.pages, args.gap)
            (ROOT / "work" / f"campus_{school}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
            )
            all_rows.extend(rows)
            print(f"{school}: postings={len(rows)} companies={len({r['company'] for r in rows})}", flush=True)

    found = {r["company"] for r in all_rows}
    hit = match_targets(targets, found)
    new_hit = [n for n in uncovered if hit.get(n)]
    lines = [
        f"postings={len(all_rows)} board_companies={len(found)} uncovered={len(uncovered)}",
        f"targets_matched={len(hit)} newly_covered={len(new_hit)}",
        "",
    ]
    for n in new_hit:
        ent = hit[n]
        cnt = sum(1 for r in all_rows if r["company"] in ent)
        samples = [r for r in all_rows if r["company"] in ent][:2]
        schools = sorted({r["school"] for r in all_rows if r["company"] in ent})
        lines.append(
            f"{n}\t{ent}\t{cnt}\t{','.join(schools)}\t"
            + " | ".join(f"{s['title'][:24]}@{s['date']}" for s in samples)
        )
    (ROOT / "work" / "_campus_match_all.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"matched={len(hit)} newly={len(new_hit)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
