"""Wayback CDX 枚举招聘平台子域（根 URL 过滤，直接得到租户主机名）。

2026-10-28 实测：`filter=original:https?://[a-z0-9-]+\\.zhiye\\.com/?$` + `collapse=urlkey`
一次返回 1,649 个北森租户主机；jobs.feishu.cn 138 个。CDX 偶发 503/504，需要重试。
输出 work/wayback_hosts.json（与 sd_center.json / code_hosts.json 同形状，按域名分组）。

用法：python work/wayback_ats_hosts.py [--max-pages 40]
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "work" / "wayback_hosts.json"
BASE = "https://web.archive.org/cdx/search/cdx"
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DOMAINS = ["zhiye.com", "jobs.feishu.cn", "hotjob.cn", "tupu360.com"]


def fetch(params: dict, tries: int = 4) -> httpx.Response | None:
    for attempt in range(tries):
        try:
            r = httpx.get(BASE, params=params, headers=HEAD, timeout=150, follow_redirects=True)
            if r.status_code == 200 and r.text.strip():
                return r
            print(f"    retry {attempt} {r.status_code} {len(r.text)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"    exc {attempt} {type(exc).__name__} {str(exc)[:60]}", flush=True)
        time.sleep(4 + attempt * 3)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=40)
    args = ap.parse_args()

    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for dom in DOMAINS:
        hosts = set(data.get(dom, []))
        before = len(hosts)
        pat = rf"original:https?://[a-z0-9-]+\.{re.escape(dom)}/?$"
        for page in range(args.max_pages):
            r = fetch({"url": dom, "matchType": "domain", "fl": "original", "filter": pat,
                       "collapse": "urlkey", "limit": "5000", "page": str(page), "output": "json"})
            if r is None:
                print(f"{dom} page {page} 放弃", flush=True)
                break
            try:
                rows = json.loads(r.text)
            except json.JSONDecodeError:
                print(f"{dom} page {page} 非 JSON，放弃", flush=True)
                break
            got = 0
            for row in rows[1:]:
                m = re.match(r"https?://([^/:]+)", row[0])
                if m and m.group(1).lower() not in hosts:
                    hosts.add(m.group(1).lower())
                    got += 1
            print(f"{dom} page {page}: +{got} 累计 {len(hosts)}", flush=True)
            if got == 0 and page > 0:
                break
            data[dom] = sorted(hosts)
            OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"{dom} 完成：{before} -> {len(hosts)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
