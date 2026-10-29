"""对已有 workday 主机逐个查 CDX，抽取 /wday/cxs/{tenant}/{site}/ 段。"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "src")
from jobradar.adapters.base import make_client

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "work" / "wd_site_probe.jsonl"
PAT = re.compile(r"/wday/cxs/([^/]+)/([^/]+)/")

hosts = []
for line in (ROOT / "work" / "cc_hosts.tsv").read_text(encoding="utf-8").splitlines():
    parts = line.split("\t")
    if parts and parts[0] == "workday":
        hosts.append(parts[1])
hosts = sorted(set(hosts))
done = set()
if OUT.exists():
    for line in OUT.read_text(encoding="utf-8").splitlines():
        try:
            done.add(json.loads(line)["host"])
        except Exception:
            pass
todo = [h for h in hosts if h not in done]
print("todo", len(todo), "done", len(done), flush=True)

def work(host):
    c = make_client()
    url = (f"https://web.archive.org/cdx/search/cdx?url={host}&matchType=host"
           f"&output=json&fl=original&collapse=urlkey&limit=200&filter=original:.*wday/cxs/.*")
    try:
        r = c.get(url, timeout=60)
        if r.status_code != 200 or not r.text.strip().startswith("["):
            return {"host": host, "pairs": [], "status": r.status_code}
        rows = r.json()
        pairs = []
        for row in rows[1:]:
            m = PAT.search(row[0] if isinstance(row, list) else str(row))
            if m:
                pairs.append([m.group(1), m.group(2)])
        uniq = [list(x) for x in {tuple(p) for p in pairs}]
        return {"host": host, "pairs": uniq, "status": 200}
    except Exception as e:
        return {"host": host, "pairs": [], "status": str(type(e).__name__)}

with OUT.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=6) as ex:
    for res in ex.map(work, todo):
        fh.write(json.dumps(res, ensure_ascii=False) + "\n")
        fh.flush()
        if res["pairs"]:
            print("SITE", res["host"], res["pairs"][:2], flush=True)
print("DONE", flush=True)
