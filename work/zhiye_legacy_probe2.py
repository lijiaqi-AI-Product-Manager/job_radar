"""老版北森门户：除了 campus/social/alljob，再从根页里找其它入口链接（jobs/portal/zhaopin/recruit…）。"""
import json
import re
import sys

sys.path.insert(0, "src")
import os
from concurrent.futures import ThreadPoolExecutor

import httpx

from jobradar.adapters import beisen_legacy as bl

PATH = "work/zhiye_hosts_all.txt"
hosts = [h.strip() for h in open(PATH, encoding="utf-8")] if os.path.exists(PATH) else []
if not hosts:
    with open("work/zhiye_legacy_probe.jsonl", encoding="utf-8") as fh:
        hosts = sorted({json.loads(line)["host"] for line in fh if line.strip()})
print("hosts", len(hosts), flush=True)
LINK = re.compile(r'href="[^"]*?/(campus|social|alljob|jobs|portal|zhaopin|recruit|job)/', re.I)
out = []
def work(h):
    try:
        with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=15) as c:
            r = c.get(f"https://{h}/")
            if r.status_code != 200:
                return
            body = r.text
            if len(bl.ROW.findall(body)) >= 3:
                out.append({"host": h, "portal": r.url.path.strip("/") or "", "rows": len(bl.ROW.findall(body)), "via": "root"})
                return
            paths = {m.group(0).split("/")[-2] for m in LINK.finditer(body)}
            for p in sorted(paths)[:4]:
                rr = c.get(f"https://{h}/{p}/")
                n = len(bl.ROW.findall(rr.text)) if rr.status_code == 200 else 0
                if n >= 3:
                    out.append({"host": h, "portal": p, "rows": n, "via": "link"})
                    return
    except Exception:
        return
with ThreadPoolExecutor(max_workers=10) as pool:
    list(pool.map(work, hosts))
out.sort(key=lambda r: -r["rows"])
with open("work/zhiye_legacy_probe2.jsonl", "w", encoding="utf-8", newline="\n") as fh:
    for r in out:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("hits", len(out))
for r in out[:20]:
    print(r["rows"], r["host"], r["portal"], r["via"])
