"""从已确认的「招聘官网」反查 ATS 入口：不猜租户名，直接看页面自己暴露了什么。

三条路径（成本从低到高，命中即停）：

  1. URL 本身就是平台门户（`x.zhiye.com` / `x.hotjob.cn` / `x.jobs.feishu.cn`）→ 直接记租户；
  2. 页面挂在公司自己域名上，但把北森列表接口原样挂在同域（白标门户，
     如 `zhaopin.joyoung.com/api/Jobad/GetJobAdPageList`）→ 打一次列表接口即可确认，
     `host` 直接写这个域名，不需要知道 tenant；
  3. 页面 HTML 里出现平台指纹（`hotjob.cn` / `mokahr.com` / `myworkdayjobs.com` /
     `tupu360` / `feishu.cn/atsx`）→ 抽出链接再做平台侧确认。

红线：只读公开招聘首页与公开列表接口；同 host ≥1.05s；不翻页、不抓 JD；
`mokahr.com` 一律只登记 `blocked`（加密入口，合规承诺不碰）。

用法：
    python3 work/careers_ats_harvest.py --out work/careers_ats.jsonl --workers 5 --limit 0
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
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobradar.adapters.base import USER_AGENT  # noqa: E402

UA = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"}
BEISEN_PATH = "/api/Jobad/GetJobAdPageList"
BEISEN_BODY = {
    "PageIndex": 0, "PageSize": 6, "KeyWords": "", "SpecialType": 0, "PortalId": "",
    "DisplayFields": ["Category", "LocId", "PostDate", "LocNames"],
}
ZHIYE = re.compile(r"https?://([a-z0-9][a-z0-9-]*)\.zhiye\.com", re.I)
HOTJOB = re.compile(r"https?://([a-z0-9][a-z0-9-]*)\.hotjob\.cn", re.I)
FEISHU = re.compile(r"https?://([a-z0-9][a-z0-9-]*)\.jobs\.feishu\.cn", re.I)
WORKDAY = re.compile(r"https?://([a-z0-9][a-z0-9-]*)\.(wd\d+)\.myworkdayjobs\.com", re.I)
MOKA = re.compile(r"https?://([a-z0-9.-]*mokahr\.com)(/[^\"'\s<>]*)", re.I)
TUPU = re.compile(r"https?://jobs\.([a-z0-9][a-z0-9-]*)\.com\.cn/([a-z0-9-]+)", re.I)

_lock = threading.Lock()
_last: dict[str, float] = {}


def throttle(host: str) -> None:
    while True:
        with _lock:
            wait = _last.get(host, 0.0) + 1.05 - time.time()
            if wait <= 0:
                _last[host] = time.time()
                return
        time.sleep(min(wait, 0.4))


def urls_of(row: dict) -> list[str]:
    out: list[str] = []
    best = (row.get("best") or {}).get("url")
    if best:
        out.append(best)
    for a in row.get("all") or []:
        u = a.get("url")
        if u and u not in out:
            out.append(u)
    home = row.get("home")
    if home and home not in out:
        out.insert(0, home)
    return out[:4]


def beisen_on_host(cli: httpx.Client, host: str) -> dict | None:
    throttle(host)
    try:
        r = cli.post(f"https://{host}{BEISEN_PATH}", json=BEISEN_BODY, timeout=12.0)
        if not r.text.lstrip().startswith("{"):
            return None
        d = r.json()
        if d.get("Code") != 200:
            return None
        items = d.get("Data") or []
        count = max(int(d.get("Count") or 0), len(items))
        if count <= 0:
            return None
        title = ""
        try:
            throttle(host)
            t = cli.get(f"https://{host}/", timeout=10.0).text
            m = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
            title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        except httpx.HTTPError:
            pass
        return {"kind": "beisen_host", "host": host, "count": count, "title": title,
                "sample": [str(i.get("JobAdName") or "") for i in items[:3]]}
    except (httpx.HTTPError, ValueError):
        return None


def scan_page(cli: httpx.Client, url: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return {"kind": "none"}
    # 1) URL 本身就是平台门户
    for pat, kind in ((ZHIYE, "beisen"), (HOTJOB, "hotjob"), (FEISHU, "feishu_atsx")):
        m = pat.search(url)
        if m:
            return {"kind": kind, "slug": m.group(1).lower(), "via": "url"}
    throttle(host)
    try:
        r = cli.get(url, timeout=15.0)
    except httpx.HTTPError as e:
        return {"kind": "none", "err": type(e).__name__, "host": host}
    final = str(r.url)
    for pat, kind in ((ZHIYE, "beisen"), (HOTJOB, "hotjob"), (FEISHU, "feishu_atsx")):
        m = pat.search(final)
        if m:
            return {"kind": kind, "slug": m.group(1).lower(), "via": "redirect"}
    body = r.text[:200000]
    # 2) 白标北森：同域挂列表接口
    hit = beisen_on_host(cli, host)
    if hit:
        hit["via"] = "page+host"
        return hit
    # 3) 页面指纹
    if MOKA.search(body):
        m = MOKA.search(body)
        return {"kind": "moka_blocked", "host": m.group(1).lower(), "via": "page"}
    m = WORKDAY.search(body)
    if m:
        return {"kind": "workday", "slug": m.group(1).lower(), "wd": m.group(2).lower(), "via": "page"}
    m = TUPU.search(body)
    if m:
        return {"kind": "tupu360", "slug": m.group(1).lower(), "tenant": m.group(2).lower(), "via": "page"}
    m = ZHIYE.search(body)
    if m:
        return {"kind": "beisen", "slug": m.group(1).lower(), "via": "page"}
    m = HOTJOB.search(body)
    if m:
        return {"kind": "hotjob", "slug": m.group(1).lower(), "via": "page"}
    m = FEISHU.search(body)
    if m:
        return {"kind": "feishu_atsx", "slug": m.group(1).lower(), "via": "page"}
    if "wecruit" in body or "/wt/" in body:
        return {"kind": "hotjob_probable", "slug": host.split(".")[0], "via": "page"}
    return {"kind": "none", "host": host, "status": r.status_code}


def work_one(row: dict) -> dict:
    name = row.get("company") or row.get("name") or ""
    out = {"company": name, "sector": row.get("sector"), "found": None, "tried": []}
    with httpx.Client(headers=UA, follow_redirects=True, timeout=15.0) as cli:
        for u in urls_of(row):
            out["tried"].append(u)
            res = scan_page(cli, u)
            if res.get("kind") not in (None, "none"):
                out["found"] = {**res, "url": u}
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/careers_ats.jsonl")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    rows: list[dict] = []
    for f in ("work/careers_confirmed.jsonl", "work/home_found.jsonl", "work/careers_final.jsonl"):
        p = ROOT / f
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                rows.append(json.loads(ln))
    seen: set[str] = set()
    uniq: list[dict] = []
    for r in rows:
        n = r.get("company")
        if n and n not in seen:
            seen.add(n)
            uniq.append(r)
    out = ROOT / a.out
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [r for r in uniq if r.get("company") not in done]
    if a.only:
        want = set(json.loads(Path(a.only).read_text(encoding="utf-8")))
        todo = [r for r in todo if r.get("company") in want]
    if a.limit:
        todo = todo[: a.limit]
    print(f"待查 {len(todo)} 家（已有结果 {len(done)}），并发 {a.workers}", flush=True)

    hits = 0
    t0 = time.time()
    with out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(work_one, r): r for r in todo}
        for i, fut in enumerate(futs, 1):
            try:
                rec = fut.result()
            except Exception as e:  # noqa: BLE001
                rec = {"company": futs[fut].get("company"), "found": None, "err": type(e).__name__}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if rec.get("found"):
                hits += 1
                fd = rec["found"]
                print(f"HIT {rec['company']:14s} {fd['kind']:15s} {fd.get('slug') or fd.get('host') or ''}", flush=True)
            if i % 40 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(todo)} {el:.0f}s 命中 {hits} ({el / i:.2f}s/家)", flush=True)
    print(f"完成 {len(todo)}，命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
