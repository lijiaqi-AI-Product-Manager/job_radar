"""把「已确认招聘页」里指向平台门户、但还没建源的目标捞出来，逐个探活。"""
import json
import re
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "work")
from concurrent.futures import ThreadPoolExecutor

import httpx
from verify_tenants_found import beisen_probe, core, feishu_probe, hotjob_probe

from jobradar.sources import load_sources

rows = [json.loads(line) for line in open("work/careers_confirmed.jsonl", encoding="utf-8") if line.strip()]
src = load_sources("sources")
have_co = {core(s.company) for s in src}
have_b = {str((s.params or {}).get("tenant", "")).lower() for s in src}
have_f = {str((s.params or {}).get("base_url", "")).split("//")[-1].split(".")[0].lower() for s in src}
have_h = {str((s.params or {}).get("tenant", "")).lower() for s in src if "hotjob" in s.adapter}

PAT = re.compile(r"https?://([a-z0-9][a-z0-9-]{1,40})\.(zhiye\.com|hotjob\.cn|jobs\.feishu\.cn)", re.I)
todo = []
for r in rows:
    co = r.get("company") or ""
    if not co or core(co) in have_co:
        continue
    urls = [((r.get("best") or {}).get("url") or "")] + [a.get("url") or "" for a in (r.get("all") or [])]
    for u in urls:
        m = PAT.search(u or "")
        if not m:
            continue
        slug, dom = m.group(1).lower(), m.group(2).lower()
        if dom == "zhiye.com" and slug in have_b:
            continue
        if dom == "jobs.feishu.cn" and slug in have_f:
            continue
        if dom == "hotjob.cn" and slug in have_h:
            continue
        todo.append({"company": co, "slug": slug, "kind": "beisen" if dom == "zhiye.com" else
                     ("feishu_atsx" if dom == "jobs.feishu.cn" else "hotjob")})
        break
print("todo", len(todo), flush=True)
out = []
def work(t):
    try:
        with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=25) as c:
            fn = {"beisen": beisen_probe, "hotjob": hotjob_probe, "feishu_atsx": feishu_probe}[t["kind"]]
            r = fn(c, t["slug"])
            if r.get("ok"):
                out.append({"platform": t["kind"], "slug": t["slug"], "company": t["company"],
                            "count": int(r.get("count") or 0), "title": r.get("title") or ""})
    except Exception:
        return
with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(work, todo))
out.sort(key=lambda x: -x["count"])
open("work/careers_platform_hits.jsonl", "w", encoding="utf-8", newline="\n").write(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
print("alive", len(out))
for r in out[:25]:
    print(r["platform"], r["slug"], r["count"], r["company"][:14], r["title"][:34])
