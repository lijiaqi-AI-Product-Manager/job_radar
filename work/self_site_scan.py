"""Scan confirmed careers pages of uncovered targets for ATS fingerprints."""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "src")
import yaml

from jobradar.adapters.base import make_client
from jobradar.pipeline.calendar import match_targets
from jobradar.sources import load_sources

doc = yaml.safe_load(open("targets/top_companies.yaml", encoding="utf-8"))
companies = {source.company for source in load_sources("sources")}
matched = match_targets(doc, companies)
uncovered = {name for name, hit in matched.items() if not hit}

urls: dict[str, str] = {}
for path in (
    "work/careers_confirmed.jsonl",
    "work/careers_final.jsonl",
    "work/home_found.jsonl",
):
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        best = row.get("best") or {}
        url = best.get("url") or row.get("home")
        if url:
            urls.setdefault(row.get("company", ""), url)

todo = [(name, urls[name]) for name in uncovered if name in urls]
print("todo", len(todo))

SIG = [
    ("beisen", r"\.zhiye\.com"),
    ("hotjob", r"hotjob\.cn"),
    ("feishu", r"\.jobs\.feishu\.cn"),
    ("workday", r"myworkdayjobs"),
    ("moka", r"mokahr"),
    ("gllue", r"gllue\.com"),
    ("tupu360", r"tupu360"),
    ("avature", r"avature"),
    ("radancy", r"radancy"),
    ("dayee", r"wecruit|dayee"),
    ("liepin", r"liepin"),
    ("zhaopin", r"zhaopin"),
    ("51job", r"51job"),
    ("boss", r"zhipin\.com"),
    ("greenhouse", r"greenhouse\.io"),
    ("lever", r"lever\.co"),
    ("smartrecruiters", r"smartrecruiters"),
    ("nextjs", r"__NEXT_DATA__"),
    ("jsonapi", r'"(/api/[^"]{3,60})"'),
]

client = make_client()
results = []


def scan(item: tuple[str, str]) -> dict:
    name, url = item
    try:
        resp = client.get(url, follow_redirects=True)
        body = resp.text[:400000]
        hits = [key for key, pattern in SIG if re.search(pattern, body, re.I)]
        return {
            "company": name,
            "url": url,
            "status": resp.status_code,
            "size": len(body),
            "final": str(resp.url),
            "hits": hits,
        }
    except Exception as exc:
        return {
            "company": name,
            "url": url,
            "status": 0,
            "size": 0,
            "final": "",
            "hits": [],
            "err": type(exc).__name__,
        }


with ThreadPoolExecutor(max_workers=8) as pool:
    futures = [pool.submit(scan, item) for item in todo]
    for done, future in enumerate(as_completed(futures), 1):
        results.append(future.result())
        if done % 80 == 0:
            print("done", done, flush=True)

with open("work/self_scan.jsonl", "w", encoding="utf-8", newline="\n") as handle:
    for row in results:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")

print("saved", len(results))
