"""新发现 ATS 租户的**实测核数**：复用真实适配器，只把网络层换成 httpx 客户端。

为什么不用 `jobradar crawl` 一条条跑：那会真写库、还要处理开闭状态；
这里只要一个数字——「这个租户有几条岗位」+「JD 有没有正文」，用来决定收不收进 sources/。
实现上直接实例化适配器，`sleep` 设成空函数（限速由外层每主机 1 rps 保证）。

用法：
    python3 work/count_tenants.py --in /tmp/exp/new_tenants.json --out /tmp/exp/counts.json
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT, load_all  # noqa: E402
from jobradar.models import SourceConfig  # noqa: E402

LOCK = threading.Lock()
LAST: dict[str, float] = {}
RPS = 1.0


def throttle(host_key: str) -> None:
    """每主机 1 rps。"""
    with LOCK:
        gap = time.time() - LAST.get(host_key, 0.0)
        wait = max(0.0, (1.0 / RPS) - gap)
        LAST[host_key] = time.time() + wait
    if wait:
        time.sleep(wait)


class Throttled(httpx.BaseTransport):
    """在传输层做限速：适配器内部的每个请求都会经过这里。"""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        throttle(request.url.host)
        return self.inner.handle_request(request)


def make_source(ats: str, company: str, tenant: str, host: str = "") -> SourceConfig:
    if ats == "beisen":
        params = {"tenant": tenant, "max_pages": 1, "page_size": 50}
        types = ["campus", "social", "intern"]
    elif ats == "hotjob":
        params = {"tenant": tenant, "max_pages": 1, "page_size": 50, "fetch_detail": False}
        if host:
            params["host"] = host
        types = ["campus", "social"]
    elif ats == "feishu_atsx":
        params = {"base_url": f"https://{tenant}.jobs.feishu.cn", "website_path": "index",
                  "portal_type": 3, "page_size": 100, "max_pages": 2}
        types = ["campus", "intern", "social"]
    else:
        raise ValueError(ats)
    return SourceConfig(
        id=f"{ats}-{tenant}".lower()[:40], company=company, adapter=ats,
        params=params, recruit_types=types, rate_limit_rps=1.0,
        compliance={"checked_on": "2026-10-27", "robots": "allowed",
                    "terms": "公开列表接口，无需登录/签名", "notes": "count_tenants 实测"},
    )


def probe(item: dict) -> dict:
    ats, company, tenant = item["ats"], item["company"], item["tenant"]
    host = item.get("host", "")
    res = {"ats": ats, "company": company, "tenant": tenant, "host": host,
           "n": 0, "jd": 0, "err": ""}
    try:
        src = make_source(ats, company, tenant, host)
        cls = load_all()[ats]
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                          follow_redirects=True,
                          transport=Throttled(httpx.HTTPTransport())) as cli:
            ad = cls(src, cli, sleep=lambda s: None)
            jobs = []
            for j in ad.fetch_all():
                jobs.append(j)
                if len(jobs) >= 200:
                    break
        res["n"] = len(jobs)
        res["jd"] = sum(1 for j in jobs if (j.description or "").strip())
    except Exception as e:  # noqa: BLE001
        res["err"] = f"{type(e).__name__}: {str(e)[:80]}"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    items = json.loads(Path(a.src).read_text(encoding="utf-8"))
    print(f"核数 {len(items)} 个租户", flush=True)
    t0 = time.time()
    out = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(probe, items):
            out.append(r)
            flag = "OK " if r["n"] else ("ERR" if r["err"] else "空 ")
            print(f"{flag} {r['ats']:10s} {r['company']:14s} {r['tenant']:22s} "
                  f"n={r['n']:<4} jd={r['jd']:<4} {r['err'][:50]}", flush=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
