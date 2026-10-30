"""自建站两跳扫描：从已知招聘页出发，找到真正的岗位列表页并数岗位。

第一跳：拿 careers_confirmed 里的 best.url，抽页面里像「招聘/职位/加入我们/careers/jobs」的链接。
第二跳：逐个打开这些链接，用三种证据数岗位——JSON-LD JobPosting、h3 岗位块、岗位式锚文本。
输出 work/selfsite_deep.jsonl，一公司一行。
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
JOB_WORDS = ("工程师", "经理", "专员", "主管", "设计师", "分析师", "顾问", "实习生",
             "总监", "运营", "技术员", "销售", "会计", "助理", "研究员", "教师", "医师", "护士")
NAV_HINTS = ("招聘", "职位", "岗位", "加入", "人才", "career", "careers", "jobs", "job", "join",
             "recruit", "zhaopin", "hr")
SKIP_HOST = ("mokahr.com", "zhiye.com", "hotjob.cn", "jobs.feishu.cn", "myworkdayjobs.com",
             "zhaopin.com", "liepin.com", "51job.com", "yingjiesheng.com", "nowcoder.com",
             "gllue.com", "tupu360.com")


def fetch(client: httpx.Client, url: str) -> tuple[int, str, str]:
    try:
        r = client.get(url)
        return r.status_code, r.text, str(r.url)
    except Exception:  # noqa: BLE001
        return 0, "", url


def job_titles(html: str) -> tuple[int, list[str]]:
    """数岗位：JSON-LD 优先，其次 h3 块，再次岗位式锚文本。"""
    ld = len(re.findall(r'"@type"\s*:\s*"JobPosting"', html))
    if ld:
        return ld, []
    titles: list[str] = []
    for m in re.finditer(r"<h3[^>]*>(.*?)</h3>", html, re.S | re.I):
        t = re.sub(r"<[^>]+>", "", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        if 2 <= len(t) <= 30 and any(w in t for w in JOB_WORDS):
            titles.append(t)
    if titles:
        return len(set(titles)), list(dict.fromkeys(titles))[:6]
    anchors = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I)
    for _href, raw in anchors:
        t = re.sub(r"<[^>]+>", " ", raw)
        t = re.sub(r"\s+", " ", t).strip()
        if 4 <= len(t) <= 30 and any(w in t for w in JOB_WORDS) and "招聘" not in t:
            titles.append(t)
    uniq = list(dict.fromkeys(titles))[:6]
    return len(uniq), uniq


def nav_links(base: str, html: str) -> list[str]:
    out: list[str] = []
    host = urlparse(base).netloc
    for href, raw in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", raw).lower()
        if not any(h in text for h in NAV_HINTS) and not any(h in href.lower() for h in NAV_HINTS):
            continue
        full = urljoin(base, href)
        if any(s in full for s in SKIP_HOST) or not full.startswith("http"):
            continue
        if urlparse(full).netloc != host:
            continue
        if full not in out and len(out) < 5:
            out.append(full)
    return out


def scan(company: str, url: str) -> dict:
    row = {"company": company, "url": url, "status": 0, "best": "", "jobs": 0, "titles": []}
    if any(s in url for s in SKIP_HOST):
        row["status"] = -1
        return row
    with httpx.Client(timeout=18, headers={"User-Agent": UA}, follow_redirects=True) as client:
        status, html, final = fetch(client, url)
        row["status"], row["best"] = status, final
        if status != 200 or len(html) < 800:
            return row
        n, titles = job_titles(html)
        best_n, best_titles = n, titles
        navs = [u for u in nav_links(final, html) if u != final]
        for nav in navs:
            st, h2, f2 = fetch(client, nav)
            if st != 200 or len(h2) < 800:
                continue
            n2, t2 = job_titles(h2)
            if n2 > best_n:
                best_n, best_titles, row["best"] = n2, t2, f2
            if best_n >= 5:
                break
    row["jobs"], row["titles"] = best_n, best_titles
    return row


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    rows = [json.loads(line) for line in open("work/careers_confirmed.jsonl", encoding="utf-8")]
    pairs: dict[str, str] = {}
    for r in rows:
        best = (r.get("best") or {}).get("url") or ""
        if best:
            pairs.setdefault(r["company"], best)
    items = list(pairs.items())[:limit] if limit else list(pairs.items())
    print(f"scan {len(items)} companies", flush=True)
    done = 0
    with open("work/selfsite_deep.jsonl", "w", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(scan, c, u): c for c, u in items}
        for fut in as_completed(futs):
            try:
                row = fut.result()
            except Exception as e:  # noqa: BLE001
                row = {"company": futs[fut], "url": "", "status": 0, "jobs": 0, "err": str(e)}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(items)}", flush=True)
    hits = [json.loads(line) for line in open("work/selfsite_deep.jsonl", encoding="utf-8")]
    good = [h for h in hits if h.get("jobs", 0) >= 2]
    print(f"done {len(hits)}; jobs>=2: {len(good)}; total jobs: {sum(h.get('jobs', 0) for h in hits)}")


if __name__ == "__main__":
    main()
