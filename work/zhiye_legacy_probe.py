import glob
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "src")
from jobradar.adapters import beisen_legacy as bl
from jobradar.adapters.base import make_client
from jobradar.sources import load_sources

DENY = {"www","m","portal-oss","acdn","campus","beisen","zhiye","static","cdn"}
have = {str((s.params or {}).get("tenant","")).lower() for s in load_sources("sources")}
hosts = set()
for path in glob.glob("work/*"):
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    for m in re.finditer(r"([a-z0-9][a-z0-9-]{1,40})\.zhiye\.com", text, re.I):
        h = m.group(1).lower()
        if h in DENY or h.startswith("2f") or h.isdigit() or len(h) < 3:
            continue
        hosts.add(h)
todo = sorted(h for h in hosts if h not in have)
print("todo", len(todo), flush=True)
client = make_client()

def scan(h):
    base = f"https://{h}.zhiye.com"
    for portal in ("campus", "social", "alljob"):
        try:
            r = client.get(f"{base}/{portal}", params={"PageIndex": 1} if portal != "alljob" else {"o": 1})
            if r.status_code != 200:
                continue
            rows = bl.ROW.findall(r.text)
            if rows:
                tm = re.search(r"<title>(.*?)</title>", r.text, re.S | re.I)
                title = re.sub(r"\s+", " ", tm.group(1)).strip()[:60] if tm else ""
                return {"host": h, "portal": portal, "rows": len(rows), "title": title}
        except Exception:
            pass
    return None

out = []
with ThreadPoolExecutor(max_workers=10) as pool:
    futures = [pool.submit(scan, h) for h in todo]
    for i, f in enumerate(as_completed(futures), 1):
        r = f.result()
        if r:
            out.append(r)
        if i % 400 == 0:
            print("done", i, "hits", len(out), flush=True)
out.sort(key=lambda x: -x["rows"])
with open("work/zhiye_legacy_probe.jsonl", "w", encoding="utf-8", newline="\n") as fh:
    for row in out:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
print("legacy-hosts", len(out))
for row in out[:25]:
    print(row["host"], row["portal"], row["rows"], row["title"])
