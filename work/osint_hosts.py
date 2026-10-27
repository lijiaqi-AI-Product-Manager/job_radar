"""被动 DNS / 站点扫描 API 枚举招聘平台子域（零猜测、只看公开归档）。

三个免费接口（2026-10-28 实测可用，无需 key）：
- api.hackertarget.com/hostsearch?q=zhiye.com      → 逗号分隔 `host,ip`，单次约 30 条
- rapiddns.io/subdomain/zhiye.com?full=1           → HTML 表格，约 26 条（免费页只有一页）
- urlscan.io/api/v1/search/?q=domain:zhiye.com     → 结构化 JSON，`total` 很小（几十条）
另试 otx.alienvault.com（匿名 429）与 crt.sh（只有通配符证书）——都不可用，代码里留注释不实现。

输出：work/osint_hosts.tsv（`platform \t host \t source`）
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
DOMAINS = [("beisen", "zhiye.com"), ("hotjob", "hotjob.cn"), ("feishu", "jobs.feishu.cn")]
PAT = {
    "beisen": re.compile(r"\b([a-z0-9][a-z0-9\-]{1,40})\.zhiye\.com\b", re.I),
    "hotjob": re.compile(r"\b([a-z0-9][a-z0-9\-]{1,40})\.hotjob\.cn\b", re.I),
    "feishu": re.compile(r"\b([a-z0-9][a-z0-9\-]{1,40})\.jobs\.feishu\.cn\b", re.I),
}


def harvest(client: httpx.Client, platform: str, domain: str) -> set[str]:
    out: set[str] = set()
    pat = PAT[platform]
    # 1) hackertarget：纯文本一行一条 `host,ip`
    try:
        r = client.get(f"https://api.hackertarget.com/hostsearch/?q={domain}", timeout=30.0)
        if r.status_code == 200:
            out |= {m.group(1).lower() for m in pat.finditer(r.text)}
    except httpx.HTTPError:
        pass
    time.sleep(1.0)
    # 2) rapiddns：HTML 表格
    try:
        r = client.get(f"https://rapiddns.io/subdomain/{domain}?full=1", timeout=30.0)
        if r.status_code == 200:
            out |= {m.group(1).lower() for m in pat.finditer(r.text)}
    except httpx.HTTPError:
        pass
    time.sleep(1.0)
    # 3) urlscan：JSON，按 page url 取子域
    try:
        r = client.get(f"https://urlscan.io/api/v1/search/?q=domain:{domain}&size=100", timeout=30.0)
        if r.status_code == 200:
            for item in (r.json().get("results") or []):
                page = (item.get("page") or {}).get("url") or ""
                out |= {m.group(1).lower() for m in pat.finditer(page)}
    except (httpx.HTTPError, ValueError):
        pass
    return out


def main() -> None:
    path = WORK / "osint_hosts.tsv"
    known: set[tuple[str, str]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            p = line.split("\t")
            if len(p) >= 2:
                known.add((p[0], p[1]))
    hits: dict[tuple[str, str], str] = {}
    with httpx.Client(headers=UA, verify=False, follow_redirects=True) as client:
        for platform, domain in DOMAINS:
            found = harvest(client, platform, domain)
            print(f"{domain}: {len(found)} hosts", flush=True)
            for h in found:
                if h in {"www", "m", "api", "careers", "campus"}:
                    continue
                key = (platform, h)
                if key in known:
                    continue
                hits[key] = "osint"
    with open(path, "a", encoding="utf-8") as f:
        for (platform, host) in sorted(hits):
            f.write(f"{platform}\t{host}\tosint\n")
    print(f"新增 {len(hits)} 条 → work/osint_hosts.tsv", flush=True)
    if "-v" in sys.argv:
        for k in sorted(hits):
            print(k)


if __name__ == "__main__":
    main()
