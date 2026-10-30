"""高校就业网「招聘信息」列表抓取 + 目标公司匹配。

当前支持南开（/correcruit/index/p/N.html，列表里带公司名）。
用法：python work/campus_harvest.py --pages 60 --out work/campus_nankai.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

ITEM = re.compile(
    r'<li>\s*<div class="date">\s*<span class="day">(\d+)</span>\s*<span class="year">([\d.]+)</span>\s*</div>\s*'
    r'<div class="title1"><a href="([^"]+)"[^>]*>(.*?)</a></div>\s*'
    r'<div class="company">\s*<a href="([^"]+)"[^>]*>【(.*?)】</a>(.*?)</div>',
    re.S,
)
CLEAN = re.compile(r"\s+")


def parse_page(html: str) -> list[dict]:
    out = []
    for day, ym, url, title, _curl, company, meta in ITEM.findall(html):
        parts = [p.strip() for p in CLEAN.sub(" ", meta).strip().split("/")]
        out.append(
            {
                "school": "nankai",
                "date": f"{ym}.{int(day):02d}" if ym else "",
                "title": CLEAN.sub(" ", title).strip(),
                "company": CLEAN.sub(" ", company).strip(),
                "url": "https://career.nankai.edu.cn" + url if url.startswith("/") else url,
                "meta": parts,
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=60)
    ap.add_argument("--gap", type=float, default=0.6)
    ap.add_argument("--out", default="work/campus_nankai.jsonl")
    args = ap.parse_args()

    out_path = ROOT / args.out
    rows: list[dict] = []
    seen = set()
    with httpx.Client(timeout=15.0, headers=H, follow_redirects=True, verify=False) as c:
        for page in range(1, args.pages + 1):
            url = f"https://career.nankai.edu.cn/correcruit/index/p/{page}.html"
            try:
                r = c.get(url)
            except Exception as exc:  # noqa: BLE001
                print(f"page {page} error {type(exc).__name__}", flush=True)
                continue
            items = parse_page(r.text)
            new = 0
            for it in items:
                if it["url"] in seen:
                    continue
                seen.add(it["url"])
                rows.append(it)
                new += 1
            print(f"page {page} status={r.status_code} items={len(items)} new={new} total={len(rows)}", flush=True)
            if not items:
                print("stop: empty page", flush=True)
                break
            time.sleep(args.gap)
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    covered = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, covered)
    names = [n for n, _ in target_names(targets)]
    uncovered = [n for n in names if not matched.get(n)]
    found = {r["company"] for r in rows}
    hit = match_targets(targets, found)
    new_hit = [n for n in uncovered if hit.get(n)]
    report = [
        f"postings={len(rows)} distinct_companies={len(found)}",
        f"targets_matched_by_board={len(hit)} newly_covered={len(new_hit)}",
        "",
    ]
    for n in new_hit:
        samples = [r for r in rows if r["company"] in hit[n]][:2]
        report.append(f"{n}\t{hit[n]}\t{len([r for r in rows if r['company'] in hit[n]])}\t" + " | ".join(f"{s['title']}@{s['date']}" for s in samples))
    (ROOT / "work" / "_campus_match.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"matched={len(hit)} newly={len(new_hit)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
