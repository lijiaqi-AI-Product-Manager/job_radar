"""探活 code_host_harvest 新发现的域名，产出与 code_hits.jsonl 同格式的行。"""
import json
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "work")
from concurrent.futures import ThreadPoolExecutor

import httpx
from verify_tenants_found import beisen_probe, feishu_probe, hotjob_probe

from jobradar.sources import load_sources

hosts = json.load(open("work/code_hosts.json", encoding="utf-8"))
src = load_sources("sources")
have_b = {str(s.params.get("tenant") or "").lower() for s in src if s.adapter.startswith("beisen")}
have_b |= {str(s.params.get("host") or "").split(".")[0].lower() for s in src if s.adapter.startswith("beisen")}
have_f = {str(s.params.get("base_url") or "").split("//")[-1].split(".")[0].lower() for s in src if s.adapter == "feishu_atsx"}
have_h = {str(s.params.get("host") or "").split(".")[0].lower() for s in src if s.adapter.startswith("hotjob")}

z = [h.split(".")[0] for h in hosts.get("zhiye.com", []) if h.split(".")[0].lower() not in have_b]
f = [h.split(".")[0] for h in hosts.get("jobs.feishu.cn", []) if h.split(".")[0].lower() not in have_f]
h = [x for x in hosts.get("hotjob.cn", []) if x.split(".")[0].lower() not in have_h]
print("todo zhiye", len(z), "feishu", len(f), "hotjob", len(h), flush=True)

rows = []
lock = __import__("threading").Lock()
def work(item):
    kind, slug = item
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=25) as c:
        try:
            if kind == "beisen":
                r = beisen_probe(c, slug)
            elif kind == "feishu_atsx":
                r = feishu_probe(c, slug)
            else:
                r = hotjob_probe(c, slug)
        except Exception as exc:
            r = {"ok": False, "err": type(exc).__name__}
        if r.get("ok"):
            r2 = {"platform": kind, "slug": slug, "company": r.get("company") or "",
                  "count": int(r.get("count") or 0), "title": r.get("title") or ""}
            with lock:
                rows.append(r2)
items = [("beisen", s) for s in z] + [("feishu_atsx", s) for s in f] + [("hotjob", s) for s in h]
with ThreadPoolExecutor(max_workers=12) as pool:
    list(pool.map(work, items))
rows.sort(key=lambda r: -r["count"])
with open("work/code_hosts2_hits.jsonl", "w", encoding="utf-8", newline="\n") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("alive", len(rows), flush=True)
for r in rows[:25]:
    print(r["platform"], r["slug"], r["count"], r["company"][:16], r["title"][:34])
