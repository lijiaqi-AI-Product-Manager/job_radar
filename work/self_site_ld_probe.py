"""量化自建站的可接入性：有多少招聘页直接带 JobPosting 结构化数据 / 可识别的岗位链接。"""
import json
import re
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "work")
from concurrent.futures import ThreadPoolExecutor

import httpx
from verify_tenants_found import core

from jobradar.sources import load_sources

rows = [json.loads(line) for line in open("work/careers_confirmed.jsonl", encoding="utf-8") if line.strip()]
src = load_sources("sources")
have = {core(s.company) for s in src}
seen, todo = set(), []
for r in rows:
    raw = r.get("company") or r.get("name") or ""
    best = (r.get("best") or {})
    url = best.get("url") or ""
    if not url or not raw:
        continue
    if core(raw) in have or raw in seen:
        continue
    host = url.split("//")[-1].split("/")[0].lower()
    if any(k in host for k in ("zhiye.com", "hotjob.cn", "feishu.cn", "mokahr", "zhaopin", "51job",
                               "liepin", "tupu360", "myworkdayjobs", "gllue", "italent", "dayee")):
        continue
    seen.add(raw)
    todo.append({"company": raw, "url": url, "host": host})
print("self candidates", len(todo), flush=True)
LD = re.compile(r'"@type"\s*:\s*"JobPosting"', re.I)
JOBLINK = re.compile(r'href="([^"]*(?:/job|/jobs|/position|/zhaopin|/campus|/recruit)[^"]*)"', re.I)
out = []
def work(r):
    try:
        with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=20) as c:
            resp = c.get(r["url"])
            if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
                return {"company": r["company"], "url": r["url"], "status": resp.status_code, "ld": 0, "links": 0}
            body = resp.text[:400000]
            ld = len(LD.findall(body))
            links = len(set(JOBLINK.findall(body)))
            return {"company": r["company"], "url": r["url"], "status": 200, "ld": ld, "links": links,
                    "title": (re.search(r"<title>(.*?)</title>", body, re.S | re.I).group(1).strip()[:40]
                              if re.search(r"<title>(.*?)</title>", body, re.S | re.I) else "")}
    except Exception as exc:
        return {"company": r["company"], "url": r["url"], "status": 0, "ld": 0, "links": 0, "err": type(exc).__name__}
with ThreadPoolExecutor(max_workers=12) as pool:
    out = list(pool.map(work, todo))
with open("work/self_site_ld.jsonl", "w", encoding="utf-8", newline="\n") as fh:
    for r in out:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
ok = [r for r in out if r["status"] == 200]
print("fetched", len(ok), "of", len(out), flush=True)
print("with JobPosting", sum(1 for r in ok if r["ld"]), "with job links>=3", sum(1 for r in ok if r["links"] >= 3))
for r in sorted(ok, key=lambda x: -x["ld"])[:10]:
    print(r["ld"], r["links"], r["company"], r["url"][:60])
