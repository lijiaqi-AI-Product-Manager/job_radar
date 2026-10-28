"""省域缺口公司：Wikidata 找官网 → 官网找招聘入口 → 识别 ATS。

输入 work/province_gap.json（work/province_gap.py 产出），输出 work/gap_sites.jsonl：
  {company, province, website, careers_url, ats, tenant/host, evidence}
断点续跑：已写入的公司跳过。用法：
  python work/gap_website_probe.py --workers 8 [--limit 200]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))

from verify_tenants_found import core  # noqa: E402

WD_API = "https://www.wikidata.org/w/api.php"
UA = "JobRadarCoverage/1.4.3 (https://github.com/lijiaqimun-coder/job_radar; lijiaqi.mun@gmail.com) httpx"
HEAD = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
OUT = ROOT / "work" / "gap_sites.jsonl"

ATS_PATTERNS = {
    "beisen": re.compile(r"https?://([a-z0-9][a-z0-9-]{1,30})\.zhiye\.com", re.I),
    "hotjob": re.compile(r"https?://([a-z0-9][a-z0-9-]{1,40})\.hotjob\.cn", re.I),
    "feishu_atsx": re.compile(r"https?://([a-z0-9][a-z0-9-]{1,40})\.jobs\.feishu\.cn", re.I),
    "workday": re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com", re.I),
    "tupu360": re.compile(r"https?://jobs\.([a-z0-9-]+)\.(?:com|cn)/([a-z0-9]+)/position", re.I),
    "gllue": re.compile(r"https?://([a-z0-9-]+)\.gllue\.com", re.I),
    "moka": re.compile(r"https?://(?:app|campus|job)\.mokahr\.com", re.I),
}

JOB_WORDS = re.compile(r"(招聘|人才招聘|加入我们|社会招聘|校园招聘|校招|职位|career|careers|jobs|join)", re.I)
JOB_LINK = re.compile(r"""href=["']([^"'#]{2,200})["']""", re.I)

_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(msg, flush=True)


def http(c: httpx.Client, url: str, timeout: float = 20.0) -> httpx.Response | None:
    try:
        return c.get(url, timeout=timeout, follow_redirects=True)
    except Exception:  # noqa: BLE001
        return None


def wikidata_site(c: httpx.Client, name: str) -> str | None:
    cands = [name, name.replace("股份有限公司", ""), name.replace("有限公司", ""), core(name)]
    seen: set[str] = set()
    for v in cands:
        if not v or v in seen:
            continue
        seen.add(v)
        try:
            r = c.get(WD_API, params={"action": "wbsearchentities", "search": v, "language": "zh",
                                      "uselang": "zh", "format": "json", "limit": 5}, timeout=15)
            hits = [h for h in r.json().get("search", []) if core(h.get("label", "")) == core(v)]
        except Exception:  # noqa: BLE001
            continue
        if not hits:
            continue
        qid = hits[0]["id"]
        try:
            r = c.get(WD_API, params={"action": "wbgetentities", "ids": qid, "props": "claims|labels",
                                      "format": "json"}, timeout=15)
            ent = r.json()["entities"][qid]
        except Exception:  # noqa: BLE001
            continue
        for snak in ent.get("claims", {}).get("P856", []):
            try:
                return snak["mainsnak"]["datavalue"]["value"]
            except Exception:  # noqa: BLE001
                continue
    return None


def scan_html(base: str, html: str) -> list[tuple[str, str, str]]:
    """返回 [(ats, host_or_tenant, matched_url)]"""
    found: list[tuple[str, str, str]] = []
    for ats, pat in ATS_PATTERNS.items():
        for m in pat.finditer(html):
            host = m.group(0)
            token = m.group(1) if m.groups() else ""
            found.append((ats, token, host))
    return found


def collect_links(base: str, html: str) -> list[str]:
    out: list[str] = []
    for raw in JOB_LINK.findall(html):
        url = urljoin(base, raw.strip().replace("&amp;", "&"))
        if not url.startswith("http"):
            continue
        p = urlparse(url)
        if not p.netloc:
            continue
        if JOB_WORDS.search(url) or JOB_WORDS.search(p.path):
            if url not in out:
                out.append(url)
    return out[:4]


def probe_company(c: httpx.Client, gap_row: dict) -> dict:
    name = gap_row["company"]
    out = {"company": name, "province": gap_row.get("province", ""), "website": None,
           "careers_url": None, "ats": None, "token": "", "evidence": ""}
    site = wikidata_site(c, name)
    if not site:
        out["evidence"] = "wikidata-no-site"
        return out
    out["website"] = site
    r = http(c, site)
    if r is None:
        out["evidence"] = "site-unreachable"
        return out
    html = r.text[:400000]
    hits = scan_html(str(r.url), html)
    if hits:
        ats, token, url = hits[0]
        out.update(careers_url=str(r.url), ats=ats, token=token, evidence=f"home-{ats}")
        return out
    links = collect_links(str(r.url), html)
    for link in links:
        rr = http(c, link)
        if rr is None:
            continue
        h2 = rr.text[:400000]
        hits = scan_html(str(rr.url), h2)
        if hits:
            ats, token, url = hits[0]
            out.update(careers_url=str(rr.url), ats=ats, token=token, evidence=f"link-{ats}")
            return out
        if JOB_WORDS.search(h2[:20000]):
            out.update(careers_url=str(rr.url), ats="self_built", evidence="link-jobpage")
            return out
    out["evidence"] = "no-job-link" if not links else "no-ats"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    gap = json.loads((ROOT / "work" / "province_gap.json").read_text(encoding="utf-8"))
    rows = [{"company": c["company"], "province": prov} for prov, items in gap.items() for c in items]
    done = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                done.add(core(json.loads(line)["company"]))
            except Exception:  # noqa: BLE001
                pass
    todo = [r for r in rows if core(r["company"]) not in done]
    if args.limit:
        todo = todo[: args.limit]
    log(f"gap {len(rows)} 家，已完成 {len(done)}，本轮 {len(todo)}")

    t0 = time.time()
    with httpx.Client(headers=HEAD, timeout=25) as client, OUT.open("a", encoding="utf-8") as fh:
        def work(row: dict) -> dict:
            time.sleep(0.05)
            return probe_company(client, row)

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for i, res in enumerate(ex.map(work, todo), 1):
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                fh.flush()
                if res["ats"] and res["ats"] != "self_built":
                    log(f"[{i}/{len(todo)}] {res['company']} -> {res['ats']} {res['token']}")
                elif i % 25 == 0:
                    log(f"[{i}/{len(todo)}] ... {time.time()-t0:.0f}s")

    stats: dict[str, int] = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            key = r.get("ats") or r.get("evidence") or "none"
            stats[key] = stats.get(key, 0) + 1
    log(f"done {time.time()-t0:.0f}s stats={stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
