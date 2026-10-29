"""自建站页面里通常嵌着真正的 ATS 地址（iframe/JS 配置/表单 action），从这里把租户挖出来。"""
import json
import re
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "work")
from concurrent.futures import ThreadPoolExecutor

import httpx
from verify_tenants_found import core

from jobradar.sources import load_sources

rows = [json.loads(line) for line in open("work/self_site_ld.jsonl", encoding="utf-8") if line.strip()]
ok = [r for r in rows if r.get("status") == 200]
print("pages", len(ok), flush=True)
PAT = {
    "beisen": re.compile(r"\b([a-z0-9][a-z0-9-]{1,40})\.zhiye\.com\b", re.I),
    "hotjob": re.compile(r"\b([a-z0-9][a-z0-9-]{1,40})\.hotjob\.cn\b", re.I),
    "feishu": re.compile(r"\b([a-z0-9][a-z0-9-]{1,40})\.jobs\.feishu\.cn\b", re.I),
    "tupu360": re.compile(r"\b([a-z0-9][a-z0-9-]{1,40})\.tupu360\.com\b", re.I),
}
DENY = {"www", "m", "api", "static", "cdn", "beisen", "zhiye", "hotjob", "feishu", "jobs", "portal-oss", "acdn"}
res = {}
def work(r):
    hits = {}
    try:
        with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=25) as c:
            resp = c.get(r["url"])
            body = resp.text[:600000]
            for kind, pat in PAT.items():
                for m in pat.finditer(body):
                    s = m.group(1).lower()
                    if s not in DENY:
                        hits.setdefault(kind, set()).add(s)
    except Exception:
        return r["company"], {}
    return r["company"], {k: sorted(v) for k, v in hits.items()}
with ThreadPoolExecutor(max_workers=12) as pool:
    for company, hits in pool.map(work, ok):
        if hits:
            res[company] = hits
print("pages with ATS refs", len(res), flush=True)
have = {core(s.company) for s in load_sources("sources")}
flat = []
for company, hits in res.items():
    for kind, slugs in hits.items():
        flat.append({"company": company, "kind": kind, "slugs": slugs, "covered": core(company) in have})
with open("work/self_site_ats.jsonl", "w", encoding="utf-8", newline="\n") as fh:
    for r in flat:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("uncovered companies with refs", sum(1 for r in flat if not r["covered"]) if flat else 0)
for r in flat[:20]:
    print(r["kind"], r["slugs"][:3], r["company"], "covered" if r["covered"] else "")
