"""Workday 定向核验：`robots.txt` 找 Site，`/wday/cxs/` 拿 total，一次判「这家到底能不能抓」。

为什么重写：`wd_tenant_probe.py` 用「根路径 406 = 租户存在」判定，2026-10-27 实测**495/495 个已知
租户名全部 406**——406 只是泛解析域名的应答，不区分租户，那 17,394 次探测结果已作废。
唯一可信的判据是 CXS 接口的 `total`：

    POST https://{t}.{wd}.myworkdayjobs.com/wday/cxs/{t}/{Site}/jobs
    {"appliedFacets":{},"limit":20,"offset":0,"searchText":""}
    → {"total": 2000, "jobPostings":[{title, externalPath, locationsText, postedOn}]}

`Site` 名只能从 `robots.txt` 得到（公开约定，不是逆向）：
  - `Sitemap: https://{host}/{Site}/siteMap.xml`
  - `Disallow: /{Site}/`（有的客户只给这条，如 ABB 的 `External_Career_Page`）

顺带把**列表接口的字段能力**探清楚：`jobPostings[]` 直接带 `title / locationsText /
postedOn / externalPath`，意味着 Workday 是「发布日 + 城市 100% + JD 走详情页」的优质源——
远好于北森（JD 96%、截止日 4%）。

用法：
    python3 work/wd_verify.py --tenants nvidia:intel:jd:pfizer:abb   # 冒号分隔
    python3 work/wd_verify.py --file /tmp/exp/wd_tenants.txt --out /tmp/exp/wd_ok.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

WDS = ("wd1", "wd3", "wd5", "wd12", "wd103", "wd501")
# `refreshFacet` 是接口端点被误写进 robots 的产物，不是站点名
SITE_SKIP = {"refreshfacet", "talentcommunity", "login", "search"}


def dns_ok(host: str) -> bool:
    """泛解析域名几乎总是能解析；这一步只用来跳过明确 NXDOMAIN 的 WD 编号。"""
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


def sites_of(cli: httpx.Client, host: str) -> list[str]:
    try:
        r = cli.get(f"https://{host}/robots.txt")
    except Exception:  # noqa: BLE001
        return []
    if r.status_code != 200 or not r.text:
        return []
    out: list[str] = []
    for m in re.finditer(r"/([A-Za-z0-9_\-]+)/siteMap\.xml", r.text):
        if m.group(1).lower() not in SITE_SKIP and m.group(1) not in out:
            out.append(m.group(1))
    for m in re.finditer(r"^Disallow:\s*/([A-Za-z0-9_\-]+)/\s*$", r.text, re.M):
        if m.group(1).lower() not in SITE_SKIP and m.group(1) not in out:
            out.append(m.group(1))
    return out


def count_jobs(cli: httpx.Client, host: str, tenant: str, site: str) -> dict | None:
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    try:
        r = cli.post(url, json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        if r.status_code != 200:
            return None
        d = r.json()
    except Exception:  # noqa: BLE001
        return None
    total = int(d.get("total") or 0)
    if total <= 0:
        return None
    posts = d.get("jobPostings") or []
    return {"total": total, "sample": len(posts),
            "with_city": sum(1 for p in posts if p.get("locationsText")),
            "with_date": sum(1 for p in posts if p.get("postedOn")),
            "jobs": [str(p.get("title") or "")[:40] for p in posts[:5]],
            "cities": [str(p.get("locationsText") or "")[:30] for p in posts[:3]]}


def verify(tenant: str, lock: threading.Lock) -> list[dict]:
    rows: list[dict] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0,
                      follow_redirects=True) as cli:
        for wd in WDS:
            host = f"{tenant}.{wd}.myworkdayjobs.com"
            if not dns_ok(host):
                continue
            sites = sites_of(cli, host)
            for site in sites:
                res = count_jobs(cli, host, tenant, site)
                if res:
                    rows.append({"tenant": tenant, "wd": wd, "host": host, "site": site,
                                 "url": f"https://{host}/zh-CN/{site}", **res})
    if rows:
        with lock:
            print(f"HIT {tenant:20s} " + " | ".join(
                f"{r['wd']}/{r['site']}={r['total']}" for r in rows[:3]), flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--out", default="/tmp/exp/wd_ok.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    names: list[str] = []
    if a.tenants:
        names += [x for x in a.tenants.split(":") if x]
    if a.file:
        names += [x.strip() for x in Path(a.file).read_text(encoding="utf-8").splitlines() if x.strip()]
    names = list(dict.fromkeys(names))
    print(f"核验 {len(names)} 个候选租户", flush=True)

    lock = threading.Lock()
    out = Path(a.out)
    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex, out.open("a", encoding="utf-8") as f:
        for rows in ex.map(lambda t: verify(t, lock), names):
            done += 1
            for r in rows:
                with lock:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if done % 25 == 0:
                print(f"... {done}/{len(names)}", flush=True)
    print(f"完成 {done}，结果写入 {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
