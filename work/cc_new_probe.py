"""把 Common Crawl 新批次捞到、但还没建源的主机逐个探活。

输入 work/cc_hosts.tsv（platform\thost\tcrawl\tpage），用现有探针判断：
- beisen：先打 JSON 列表接口；没有 JSON 的再看服务端渲染门户 /campus 有没有表格行。
- feishu：门户标题 + 校招/实习计数。
- hotjob：大易 SU 租户。
输出 work/cc_hits.jsonl，每行一个可用候选（含平台、租户、公司名、岗位数、判定依据）。
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "work")
import httpx
from verify_tenants_found import beisen_probe, feishu_probe, hotjob_probe

from jobradar.sources import load_sources

ROOT = Path(__file__).resolve().parent.parent
HOSTS = ROOT / "work" / "cc_hosts.tsv"
OUT = ROOT / "work" / "cc_hits.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"}

src = load_sources("sources")
have_beisen = {str((s.params or {}).get("tenant", "")).lower() for s in src}
have_feishu = {
    str((s.params or {}).get("base_url", "")).split("//")[-1].split(".")[0].lower() for s in src
}
have_hotjob = {str((s.params or {}).get("tenant", "")).upper() for s in src if "hotjob" in s.adapter}
have_legacy = {
    str((s.params or {}).get("tenant", "")).lower() for s in src if "beisen_legacy" in s.adapter
}

ROW_RE = re.compile(r"(/zpdetail/|/job_show/|campusxq\?jobId|socialxq\?jobId)")


def probe(host: str) -> dict | None:
    slug = host.split(".")[0].lower()
    client = httpx.Client(headers=UA, follow_redirects=True, timeout=20)
    try:
        if host.endswith("zhiye.com"):
            if slug in have_beisen:
                return None
            r = beisen_probe(client, slug)
            if r.get("ok") and int(r.get("count") or 0) > 0:
                return {
                    "kind": "beisen",
                    "tenant": slug,
                    "company": r.get("title"),
                    "count": int(r["count"]),
                    "why": "json",
                }
            if slug in have_legacy:
                return None
            try:
                html = client.get(f"https://{host}/campus").text
            except Exception:
                return None
            if len(html) > 2000 and ROW_RE.search(html):
                rows = len(re.findall(r"<tr", html))
                return {
                    "kind": "beisen_legacy",
                    "tenant": slug,
                    "company": None,
                    "count": rows,
                    "why": "server-rendered",
                }
            return None
        if host.endswith("jobs.feishu.cn"):
            if slug in have_feishu:
                return None
            r = feishu_probe(client, slug)
            campus = int(r.get("campus") or 0)
            if r.get("ok") and campus > 0:
                return {
                    "kind": "feishu_atsx",
                    "tenant": slug,
                    "company": r.get("title"),
                    "count": campus,
                    "why": "campus",
                }
            return None
        if host.endswith("hotjob.cn"):
            if slug in have_hotjob:
                return None
            r = hotjob_probe(client, slug)
            if r.get("ok") and int(r.get("count") or 0) > 0:
                return {
                    "kind": "hotjob",
                    "tenant": slug.upper(),
                    "company": r.get("company"),
                    "count": int(r["count"]),
                    "why": "su",
                }
            return None
        return None
    finally:
        client.close()


def main() -> int:
    hosts = []
    seen = set()
    for line in HOSTS.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        host = parts[1].strip().lower()
        if not host or host in seen:
            continue
        seen.add(host)
        hosts.append(host)
    print("hosts", len(hosts), flush=True)
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["host"])
    todo = [h for h in hosts if h not in done]
    print("todo", len(todo), flush=True)
    hits = 0
    with OUT.open("a", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=12) as pool:
            for i, res in enumerate(pool.map(probe, todo), 1):
                if res:
                    res["host"] = todo[i - 1]
                    fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                    fh.flush()
                    hits += 1
                    print("HIT", res["kind"], res["tenant"], res["count"], res.get("company"), flush=True)
                if i % 200 == 0:
                    print("progress", i, "hits", hits, flush=True)
    print("done hits", hits, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
