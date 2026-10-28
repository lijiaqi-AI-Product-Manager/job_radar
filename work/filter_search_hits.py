"""过滤 work/search_verified.jsonl：只留 count>0、主机是平台自有域、标题与公司品牌对得上的条目。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))
from verify_search_hits import brand  # noqa: E402

rows = [json.loads(ln) for ln in (ROOT / "work/search_verified.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
BAD_HOST = {"campus.hundsun.com"}
kept, drop = [], []
for r in rows:
    host = str(r.get("host") or "")
    comp = r.get("company") or ""
    title = r.get("title") or ""
    cnt = int(r.get("count") or 0)
    p = r.get("platform")
    ok_host = (p == "beisen" and host.endswith(".zhiye.com")) or (p == "hotjob" and host.endswith(".hotjob.cn"))
    ok_title = brand(comp) in brand(title) and len(brand(comp)) >= 2
    if cnt > 0 and ok_host and ok_title and host not in BAD_HOST:
        kept.append(r)
    else:
        drop.append((p, r.get("slug"), comp, cnt, title[:20], ok_host, ok_title))
print(f"保留 {len(kept)} / 总 {len(rows)}")
for d in drop:
    print("  drop", d)
(ROOT / "work/search_verified_clean.jsonl").write_text(
    "".join(json.dumps(k, ensure_ascii=False) + "\n" for k in kept), encoding="utf-8")
