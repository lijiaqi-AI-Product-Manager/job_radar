import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "src")
from jobradar.adapters.base import make_client

sites = json.load(open("work/wd_sites.json", encoding="utf-8"))

def check(item):
    host, pairs = item
    c = make_client()
    for tenant, site in pairs:
        try:
            r = c.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                       json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                       headers={"Accept": "application/json", "Content-Type": "application/json"})
            if r.status_code != 200:
                continue
            facets = (r.json() or {}).get("facets") or {}
            locs = []
            for f in facets.get("locations", []) or []:
                for v in f.get("values", []) or []:
                    if "china" in str(v.get("descriptor", "")).lower() or "中国" in str(v.get("descriptor", "")):
                        locs.append(v)
            if locs:
                title = ""
                try:
                    p = c.get(f"https://{host}/{site}", headers={"Accept": "text/html"})
                    m = re.search(r"<title>(.*?)</title>", p.text, re.S)
                    title = m.group(1).strip()[:60] if m else ""
                except Exception:
                    pass
                return (host, tenant, site, title, len(locs))
        except Exception:
            continue
    return None

out = []
with ThreadPoolExecutor(max_workers=12) as ex:
    for res in ex.map(check, sites.items()):
        if res:
            out.append(res)
            print("HIT", res, flush=True)
json.dump(out, open("work/wd_cn_sites.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("china hosts", len(out))
