"""Scan every companies.jsonl careers URL host for beisen white-label or legacy portals."""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

sys.path.insert(0, "src")
from jobradar.adapters import beisen_legacy as bl
from jobradar.adapters.base import make_client
from jobradar.sources import load_sources

known = set()
for s in load_sources("sources"):
    p = s.params or {}
    for key in ("host", "tenant", "base_url"):
        if p.get(key):
            known.add(str(p[key]).lower().replace("https://", "").replace("http://", "").strip("/"))

hosts = {}
for line in open("companies.jsonl", encoding="utf-8"):
    row = json.loads(line)
    url = row.get("careers_url") or ""
    host = (urlparse(url).hostname or "").lower()
    if host and host not in hosts and "mokahr" not in host and "zhiye" not in host:
        hosts[host] = row.get("company", "")
todo = [(h, c) for h, c in hosts.items() if h not in known and not h.endswith("hotjob.cn") and not h.endswith("feishu.cn")]
print("todo", len(todo), flush=True)
client = make_client()

def scan(item):
    host, company = item
    base = f"https://{host}"
    out = {"host": host, "company": company, "kind": "", "count": 0, "title": ""}
    try:
        r = client.get(base + "/", timeout=15, follow_redirects=True)
        html = r.text[:300000]
        m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:60] if m else ""
        if "zhiye" not in html.lower() and "beisen" not in html.lower() and "/campus" not in html.lower():
            return out
        try:
            resp = client.post(base + "/api/Jobad/GetJobAdPageList", timeout=15, json={
                "PageIndex": 1, "PageSize": 10, "DisplayFields": ["PostDate", "LocNames"], "Conditions": []},
                headers={"Accept": "application/json"})
            data = resp.json()
            count = int(data.get("Count") or 0)
            if count > 0:
                return {"host": host, "company": company, "kind": "beisen_host", "count": count, "title": out["title"]}
        except Exception:
            pass
        for portal in ("campus", "social", "alljob"):
            try:
                params = {"PageIndex": 1} if portal != "alljob" else {"o": 1}
                resp = client.get(f"{base}/{portal}", params=params, timeout=15)
                if resp.status_code == 200 and bl.ROW.findall(resp.text):
                    return {"host": host, "company": company, "kind": f"legacy_{portal}", "count": len(bl.ROW.findall(resp.text)), "title": out["title"]}
            except Exception:
                continue
        return out
    except Exception as exc:
        out["kind"] = "err:" + type(exc).__name__
        return out

results = []
with ThreadPoolExecutor(max_workers=10) as pool:
    futures = [pool.submit(scan, item) for item in todo]
    for done, future in enumerate(as_completed(futures), 1):
        results.append(future.result())
        if done % 300 == 0:
            print("done", done, "hits", sum(1 for r in results if r["count"] > 0), flush=True)

with open("work/host_ats_scan2.jsonl", "w", encoding="utf-8", newline="\n") as fh:
    for row in sorted(results, key=lambda r: -r["count"]):
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
print("hits", sum(1 for r in results if r["count"] > 0), "of", len(results))
for row in sorted(results, key=lambda r: -r["count"])[:25]:
    print(row["count"], row["kind"], row["host"], row["company"][:20], row["title"][:30])
