"""Common Crawl 索引 → 招聘平台租户枚举（结构化、零猜测、断点续跑）。

原理：`index.commoncrawl.org/<crawl>-index?url=<domain>&matchType=domain&output=json&fl=url`
按抓取批次返回该域下所有被抓过的 URL。一个租户通常 1~3 条 URL（`/`、`/robots.txt`、`/404`）。
2026-10-27 实测：CC 对该 API 限流很凶（502/504 频繁），因此必须长退避 + 多批次重试，
且 `showNumPages` 返回的 `pages` 不可靠（zhiye.com 报 1 页却仍有下一页），改为「翻到空页为止」。

用法：python work/cc_harvest.py [每批最多页数] [平台名，可选]
输出：work/cc_hosts.tsv（`platform \t host \t crawl \t page`）、work/cc_pages.json（断点状态）
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
INDEX_BASE = "https://index.commoncrawl.org"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

DOMAINS = [
    ("beisen", "zhiye.com"),
    ("hotjob", "hotjob.cn"),
    ("feishu", "jobs.feishu.cn"),
    ("tupu360", "careersite.tupu360.com"),
    ("workday", "myworkdayjobs.com"),
]

HOST_PAT = {
    "beisen": re.compile(r"^https?://([a-z0-9][a-z0-9\-]*)\.zhiye\.com"),
    "hotjob": re.compile(r"^https?://([a-z0-9][a-z0-9\-]*)\.hotjob\.cn"),
    "feishu": re.compile(r"^https?://([a-z0-9][a-z0-9\-]*)\.jobs\.feishu\.cn"),
    "tupu360": re.compile(r"^https?://([a-z0-9][a-z0-9\-]*)\.careersite\.tupu360\.com"),
    "workday": re.compile(r"^https?://([a-z0-9][a-z0-9\-]*\.wd\d+\.myworkdayjobs\.com)"),
}


def get(client: httpx.Client, url: str, tries: int = 3) -> httpx.Response | None:
    pause = 4.0
    for _ in range(tries):
        try:
            r = client.get(url)
            if r.status_code in (200, 400, 404):
                return r
            time.sleep(pause)
            pause = min(pause * 1.8, 25)
        except Exception:  # noqa: BLE001 - 超时/重置都当可重试
            time.sleep(pause)
            pause = min(pause * 1.8, 25)
    return None


def main() -> None:
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    hosts_path = WORK / "cc_hosts.tsv"
    state_path = WORK / "cc_pages.json"
    state: set[str] = set(json.loads(state_path.read_text(encoding="utf-8"))) if state_path.exists() else set()
    seen: set[tuple[str, str]] = set()
    if hosts_path.exists():
        for line in hosts_path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                seen.add((parts[0], parts[1]))

    fh = open(hosts_path, "a", encoding="utf-8")
    with httpx.Client(headers=UA, timeout=45, verify=False) as client:
        ci = get(client, f"{INDEX_BASE}/collinfo.json", tries=4)
        if ci is None:
            print("collinfo failed", flush=True)
            return
        crawls_all = [x["id"] for x in json.loads(ci.text)]
        start = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        crawls = crawls_all[start:start + 6]
        print("crawls", crawls, flush=True)
        for platform, domain in DOMAINS:
            if only and only != platform:
                continue
            pat = HOST_PAT[platform]
            for crawl in crawls:
                key0 = f"{platform}|{crawl}"
                if f"{key0}|*" in state:
                    continue
                got_new = 0
                empty = 0
                try:
                    for page in range(max_pages):
                        key = f"{key0}|{page}"
                        if key in state:
                            continue
                        url = (
                            f"{INDEX_BASE}/{crawl}-index?url={domain}&matchType=domain"
                            f"&output=json&fl=url&page={page}"
                        )
                        r = get(client, url)
                        if r is None:
                            print(f"{key}: unreachable", flush=True)
                            time.sleep(5)
                            continue
                        if r.status_code in (400, 404):
                            empty += 1
                            break
                        recs = 0
                        for line in r.text.splitlines():
                            line = line.strip()
                            if not line.startswith("{"):
                                continue
                            try:
                                u = json.loads(line).get("url", "")
                            except Exception:  # noqa: BLE001
                                continue
                            recs += 1
                            m = pat.match(u.lower())
                            if not m:
                                continue
                            host = m.group(1)
                            if (platform, host) in seen:
                                continue
                            seen.add((platform, host))
                            fh.write(f"{platform}\t{host}\t{crawl}\t{page}\n")
                            got_new += 1
                        fh.flush()
                        state.add(key)
                        if recs == 0:
                            empty += 1
                            break
                        time.sleep(2.0)
                except Exception as exc:  # noqa: BLE001 - 单批次失败不影响整体推进
                    print(f"{key0}: ERROR {type(exc).__name__}", flush=True)
                    time.sleep(3)
                    continue
                if empty:
                    state.add(f"{key0}|*")
                state_path.write_text(json.dumps(sorted(state), ensure_ascii=False), encoding="utf-8")
                print(f"{key0}: new={got_new} uniq={len(seen)} empty={empty}", flush=True)
    fh.close()
    print(f"done uniq={len(seen)}", flush=True)


if __name__ == "__main__":
    main()
