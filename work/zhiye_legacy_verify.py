import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "src")
from verify_tenants_found import core

from jobradar.adapters.base import make_client
from jobradar.adapters.beisen_legacy import BeisenLegacyAdapter
from jobradar.models import SourceConfig
from jobradar.sources import load_sources

with open("work/zhiye_legacy_probe.jsonl", encoding="utf-8") as fh:
    hits = [json.loads(line) for line in fh if line.strip()]
rows = [h for h in hits if h["rows"] >= 3]
print("candidates", len(rows), flush=True)
client = make_client()
existing = {core(s.company) for s in load_sources("sources")}
out = []
def work(row):
    cfg = {"id": f"beisen-legacy-{row['host']}", "company": row["host"], "adapter": "beisen_legacy",
           "enabled": True, "recruit_types": ["campus"], "rate_limit_rps": 1.0,
           "params": {"tenant": row["host"], "portal": row["portal"]},
           "compliance": {"checked_on": "2026-10-29", "robots": "not_applicable", "terms": "公开招聘门户列表页，无需登录、无验证码"}}
    try:
        src = SourceConfig(**cfg)
        adapter = BeisenLegacyAdapter(src, client)
        jobs = []
        for job in adapter.fetch_all():
            jobs.append(job)
            if len(jobs) >= 40:
                break
        return {"host": row["host"], "portal": row["portal"], "title": row["title"], "jobs": len(jobs), "err": ""}
    except Exception as exc:
        return {"host": row["host"], "portal": row["portal"], "title": row["title"], "jobs": 0, "err": type(exc).__name__}
results = []
lock = threading.Lock()
def run(row):
    r = work(row)
    with lock:
        results.append(r)
with ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(run, rows))
results.sort(key=lambda r: -r["jobs"])
with open("work/zhiye_legacy_verified.jsonl", "w", encoding="utf-8", newline="\n") as fh:
    for r in results:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("ok", sum(1 for r in results if r["jobs"] > 0), "of", len(results))
for r in results[:25]:
    print(r["jobs"], r["host"], r["portal"], r["title"][:40], r["err"])
