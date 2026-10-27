"""在 Common Crawl 枚举出的 Workday 主机里筛「有中国岗位」的租户。

为什么不用 CC 的 URL 反推 tenant/site：`filter=~url:` 那条索引查询一直 504/404，
直接探活更稳：GET 主页拿 site 段 → POST `/wday/cxs/{tenant}/{site}/jobs` 拿 facets →
用适配器自己的 `country_locations()` 找 China 分面 id → 带 facets 再问一次 total。

只读公开 CXS JSON，与已入库的 25 个 workday 源完全同一套请求，不涉及登录/签名。

输出：work/wd_china.jsonl（每行 {host, tenant, site, title, total}），work/wd_pairs.json 断点状态
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.workday import country_locations  # noqa: E402

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9",
}
PAIR_RE = re.compile(r"/wday/cxs/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-%]+)/")


def discover(client: httpx.Client, host: str) -> tuple[str, str, str] | None:
    """返回 (tenant, site, title)；主页打不开就退回 tenant=主机前缀 + 页面里的 site 线索。"""
    tenant = host.split(".")[0]
    title = ""
    site = ""
    try:
        r = client.get(f"https://{host}/", timeout=15.0)
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:80]
        m2 = PAIR_RE.search(str(r.url)) or PAIR_RE.search(r.text[:20000])
        if m2:
            tenant, site = m2.group(1), m2.group(2)
        if not site:
            seg = [s for s in str(r.url).split("/") if s and "." not in s]
            if seg:
                site = seg[-1]
    except httpx.HTTPError:
        pass
    return (tenant, site, title) if site else None


def china_total(client: httpx.Client, host: str, tenant: str, site: str) -> int:
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    body = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    try:
        r = client.post(url, json=body, timeout=15.0)
        d = r.json()
    except (httpx.HTTPError, ValueError):
        return 0
    ids = country_locations(d.get("facets") or [], "China")
    if not ids:
        return 0
    body["appliedFacets"] = {"locations": ids}
    body["limit"] = 5
    try:
        r2 = client.post(url, json=body, timeout=15.0)
        d2 = r2.json()
    except (httpx.HTTPError, ValueError):
        return 0
    return int(d2.get("total") or 0)


def main() -> None:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    rows = [ln.split("\t") for ln in (WORK / "cc_hosts.tsv").read_text(encoding="utf-8").splitlines() if ln.strip()]
    hosts = sorted({r[1] for r in rows if r[0] == "workday"})
    out_path = WORK / "wd_china.jsonl"
    done: set[str] = set()
    if out_path.exists():
        for ln in out_path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["host"])
            except Exception:  # noqa: BLE001
                pass
    todo = [h for h in hosts if h not in done]
    print(f"workday 主机 {len(hosts)}，待探 {len(todo)}，并发 {workers}", flush=True)

    def probe(host: str) -> dict | None:
        with httpx.Client(headers=UA, follow_redirects=True, timeout=20.0, verify=False) as c:
            got = discover(c, host)
            if not got:
                return None
            tenant, site, title = got
            total = china_total(c, host, tenant, site)
            if total <= 0:
                return None
            return {"host": host, "tenant": tenant, "site": site, "title": title, "total": total}

    t0 = time.time()
    hit = 0
    with ThreadPoolExecutor(workers) as ex, open(out_path, "a", encoding="utf-8") as f:
        for i, rec in enumerate(ex.map(probe, todo), 1):
            if not rec:
                continue
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            hit += 1
            print(f"[{i}/{len(todo)}] {rec['host']:<42} {rec['total']:>4} 中国岗  {rec['title'][:30]}", flush=True)
            if i % 100 == 0:
                print(f"... {i}/{len(todo)} {time.time() - t0:.0f}s 命中 {hit}", flush=True)
    print(f"完成：命中 {hit}，用时 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
