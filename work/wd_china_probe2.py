"""逐个 Workday 站点问「中国分面下有多少岗位」。

site 段来自 work/wd_site_discover.py（robots.txt 的 siteMap 地址）。
和适配器同一套判断：先空 appliedFacets 拿 facets，再按 descriptor 以 "China, " 开头
的 id 过滤；一个国家分面都没有的租户直接跳过（不猜、不放宽）。
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from jobradar.adapters.workday import country_locations

UA = {"User-Agent": "Mozilla/5.0 (compatible; jobradar/1.7)", "Content-Type": "application/json"}
LIST = "https://{host}/wday/cxs/{tenant}/{site}/jobs"


def probe(rec: dict, client: httpx.Client) -> dict:
    host, tenant, site = rec["host"], rec["tenant"], rec["site"]
    out = {"host": host, "tenant": tenant, "site": site, "china": 0, "total": 0, "facet": False}
    url = LIST.format(host=host, tenant=tenant, site=site)
    try:
        r = client.post(url, json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        if r.status_code != 200:
            out["status"] = r.status_code
            return out
        data = r.json()
        out["total"] = data.get("total", 0)
        ids = country_locations(data.get("facets") or [], "China")
        out["facet"] = bool(ids)
        if not ids:
            return out
        r2 = client.post(url, json={"appliedFacets": {"locations": ids}, "limit": 1, "offset": 0, "searchText": ""})
        if r2.status_code == 200:
            out["china"] = r2.json().get("total", 0)
    except Exception as e:
        out["err"] = type(e).__name__
    return out


def main() -> None:
    lines = Path("work/wd_sites.jsonl").read_text(encoding="utf-8").splitlines()
    recs = [json.loads(line) for line in lines if line.strip()]
    recs = [r for r in recs if r.get("site")]
    out_path = Path("work/wd_china2.jsonl")
    done = set()
    if out_path.exists():
        done = {json.loads(line)["host"] for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    todo = [r for r in recs if r["host"] not in done]
    print(f"candidates={len(recs)} todo={len(todo)}", flush=True)
    with httpx.Client(timeout=20, follow_redirects=False, headers=UA) as client, \
            out_path.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=8) as ex:
        for i, rec in enumerate(ex.map(lambda r: probe(r, client), todo), 1):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 100 == 0:
                print(f"{i}/{len(todo)}", flush=True)
    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    hit = [r for r in rows if r.get("china")]
    print(f"hosts={len(rows)} with China facet={sum(1 for r in rows if r.get('facet'))} china_jobs>0={len(hit)} "
          f"sum_jobs={sum(r['china'] for r in hit)}")


if __name__ == "__main__":
    main()
