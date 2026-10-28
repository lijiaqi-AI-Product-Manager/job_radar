"""Probe 北森 hosts that appeared in past recon files but never became a source."""

import glob
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "src")
from jobradar.adapters.base import make_client
from jobradar.sources import load_sources

DENY = {"www", "m", "portal-oss", "acdn", "campus", "beisen", "zhiye", "static", "cdn"}

have = {str((s.params or {}).get("tenant", "")).lower() for s in load_sources("sources")}

hosts = set()
for path in glob.glob("work/*"):
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    for match in re.finditer(r"([a-z0-9][a-z0-9-]{1,40})\.zhiye\.com", text, re.I):
        host = match.group(1).lower()
        if host in DENY or host.startswith("2f") or host.isdigit() or len(host) < 3:
            continue
        hosts.add(host)

todo = sorted(h for h in hosts if h not in have)
print("todo", len(todo))

SITE = "https://{}.zhiye.com"
client = make_client()


def probe(host: str) -> dict:
    base = SITE.format(host)
    try:
        page = client.get(base + "/")
        title_match = re.search(r"<title>(.*?)</title>", page.text, re.S | re.I)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:60] if title_match else ""
        resp = client.post(
            base + "/api/Jobad/GetJobAdPageList",
            json={
                "PageIndex": 1,
                "PageSize": 10,
                "DisplayFields": ["PostDate", "LocNames"],
                "Conditions": [],
            },
            headers={"Accept": "application/json"},
        )
        data = resp.json()
        return {
            "host": host,
            "title": title,
            "count": int(data.get("Count") or 0),
            "status": resp.status_code,
        }
    except Exception as exc:
        return {"host": host, "title": "", "count": -1, "status": 0, "err": type(exc).__name__}


results = []
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = [pool.submit(probe, host) for host in todo]
    for done, future in enumerate(as_completed(futures), 1):
        results.append(future.result())
        if done % 300 == 0:
            print("done", done, flush=True)

good = [row for row in results if row["count"] > 0]
with open("work/zhiye_leftover_probe.jsonl", "w", encoding="utf-8", newline="\n") as handle:
    for row in sorted(good, key=lambda item: -item["count"]):
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")

print("alive-with-jobs", len(good), "of", len(todo))
for row in sorted(good, key=lambda item: -item["count"])[:15]:
    print(row["host"], row["count"], row["title"])
