"""自建站「招聘公告」可行性探测：判断已确认的招聘官网页面能否当一个源。

三类证据：
- article: 页面本身就是一篇招聘公告（标题含 招聘/校招/应届，正文有日期或 JD 词）
- list:    页面是公告列表（同域 ≥3 个链接文案含 招聘/校招/校园/人才/加入）
- empty:   JS 空壳或无关页面

输出 work/notice_probe.jsonl，字段 {company, url, final, status, bytes, kind, n_links, samples, evidence}
用法：python work/notice_probe.py --limit 800 --workers 8
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
LINK_TEXT = re.compile(r"招聘|校招|校园招聘|应届|人才|加入我们|join", re.I)
ARTICLE_HINT = re.compile(r"202[5-7]|校园招聘|社会招聘|招聘公告|招聘简章|岗位职责|任职要求|简历投递")
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"[\s\u3000]+")
A = re.compile(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', re.S | re.I)


def text_of(fragment: str) -> str:
    return WS.sub(" ", TAG.sub(" ", fragment)).strip()


def probe(row: dict, client: httpx.Client) -> dict:
    company, url = row["company"], row["url"]
    rec: dict = {"company": company, "url": url}
    try:
        r = client.get(url)
        body = r.text
        rec.update(status=r.status_code, bytes=len(body), final=str(r.url))
        title = (re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I) or [None, ""])[1]
        rec["title"] = text_of(title)[:80]
        host = urlparse(str(r.url)).netloc
        links, seen = [], set()
        for href, anchor in A.findall(body):
            t = text_of(anchor)
            if not t or len(t) > 60 or not LINK_TEXT.search(t):
                continue
            full = urljoin(str(r.url), href)
            if urlparse(full).netloc != host or full in seen:
                continue
            seen.add(full)
            links.append({"text": t, "url": full})
        rec["n_links"] = len(links)
        rec["samples"] = [(lk["text"][:26], lk["url"][:90]) for lk in links[:4]]
        plain = text_of(body)
        is_article = bool(
            LINK_TEXT.search(rec["title"]) and ARTICLE_HINT.search(plain) and len(plain) > 400
        )
        if len(links) >= 3:
            rec["kind"] = "list"
        elif is_article:
            rec["kind"] = "article"
        else:
            rec["kind"] = "empty"
        rec["list_url"] = links[0]["url"] if rec["kind"] == "list" else url
    except Exception as exc:  # noqa: BLE001
        rec["kind"] = "error"
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def load_candidates(limit: int) -> list[dict]:
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    covered = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, covered)
    names = [n for n, _ in target_names(targets)]
    uncovered = {n for n in names if not matched.get(n)}

    rows, seen = [], set()
    for path in ("careers_confirmed.jsonl", "home_found.jsonl", "careers_final.jsonl"):
        p = ROOT / "work" / path
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            company = d.get("company") or d.get("name") or ""
            best = d.get("best") or {}
            url = (
                d.get("final")
                or d.get("url")
                or d.get("careers_url")
                or (best.get("url") if isinstance(best, dict) else "")
                or ""
            )
            if not company or not url.startswith("http") or company in seen:
                continue
            if company not in uncovered:
                continue
            seen.add(company)
            rows.append({"company": company, "url": url})
            if len(rows) >= limit:
                return rows
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=900)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="work/notice_probe.jsonl")
    args = ap.parse_args()

    rows = load_candidates(args.limit)
    print(f"candidates={len(rows)}", flush=True)
    out = ROOT / args.out
    with httpx.Client(timeout=20.0, headers=H, follow_redirects=True, verify=False) as client, \
            ThreadPoolExecutor(max_workers=args.workers) as pool, \
            out.open("w", encoding="utf-8") as fh:
        for i, rec in enumerate(pool.map(lambda r: probe(r, client), rows), 1):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 50 == 0:
                fh.flush()
                print(f"{i}/{len(rows)}", flush=True)
    print("done", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
