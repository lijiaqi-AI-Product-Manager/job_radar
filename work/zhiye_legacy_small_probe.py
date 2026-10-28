"""老版北森里「首屏只有 1-2 行」的小门户：用适配器实抓一页确认后再入库。"""
import json
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "work")
from concurrent.futures import ThreadPoolExecutor

from jobradar.adapters.base import make_client
from jobradar.adapters.beisen_legacy import BeisenLegacyAdapter
from jobradar.models import SourceConfig
from jobradar.sources import load_sources

with open("work/zhiye_legacy_probe.jsonl", encoding="utf-8") as fh:
    rows = [json.loads(line) for line in fh if line.strip()]
small = [r for r in rows if r["rows"] <= 2]
print("small portals", len(small), flush=True)
client = make_client()
def check(r):
    cfg = {"id": f"beisen-legacy-{r['host']}", "company": r["host"], "adapter": "beisen_legacy",
           "enabled": True, "recruit_types": ["campus"], "rate_limit_rps": 1.0,
           "params": {"tenant": r["host"], "portal": r["portal"]},
           "compliance": {"checked_on": "2026-10-29", "robots": "not_applicable",
                          "terms": "公开招聘门户列表页，无需登录、无验证码"}}
    try:
        src = SourceConfig(**cfg)
        jobs = []
        for job in BeisenLegacyAdapter(src, client).fetch_all():
            jobs.append(job)
            if len(jobs) >= 30:
                break
        return {"host": r["host"], "portal": r["portal"], "title": r["title"], "jobs": len(jobs)}
    except Exception as exc:
        return {"host": r["host"], "portal": r["portal"], "title": r["title"], "jobs": 0, "err": type(exc).__name__}
out = []
with ThreadPoolExecutor(max_workers=6) as pool:
    for res in pool.map(check, small):
        out.append(res)
out.sort(key=lambda x: -x["jobs"])
live = [r for r in out if r["jobs"] > 0]
print("live", len(live), "of", len(out), flush=True)
open("work/zhiye_legacy_small.jsonl", "w", encoding="utf-8", newline="\n").write(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
have = {__import__("re").sub(r"(股份有限公司|有限责任公司|有限公司|集团|控股)$", "", s.company) for s in load_sources("sources")}
for r in live[:25]:
    print(r["jobs"], r["host"], r["portal"], r["title"][:40])
