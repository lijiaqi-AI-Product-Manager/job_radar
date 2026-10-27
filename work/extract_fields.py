"""全量抽取：为每个公司从「真实职位列表 + 公告页 + 官微推文」抽取日历字段（十项口径）。

数据来源优先级（越靠前越硬）：
P1  ATS 结构化列表：
    - 北森新 API：POST /api/Jobad/GetJobAdPageList（PortalId 必须为空串）
    - 北森 legacy：GET /Campus?PageIndex=N&k= → <a href="/zpdetail/{id}" title="职位名">
    - 大易：POST /wecruit/positionInfo/listPosition/{SU...}
    能拿到**真实职位名**：「2027届校招-药品注册工程师」「算法工程师-上海」，
    届次/方向/城市都在名字里 —— 这是最硬的证据。
P2  招聘站首页 / 校园招聘页 / 公告列表页的正文 —— 「2027届校园招聘正式启动」「网申时间 8.3-12.31」
P3  站内公告详情页 —— 从 P2 抽到公告链接后深入一层（最多 3 条，同主机限速）
P4  官方微信公众号推文（mp.weixin.qq.com）—— 校招公告的最权威来源之一，
    README 明确允许，但必须记录 source.date（推文日期）

红线（CLAUDE.md）：
- 同主机 ≤1 请求/秒，不并发同主机；
- UA 固定为项目 UA，不伪造浏览器；
- 遇到验证码/登录墙/签名接口 → 记 blocked，不绕；
- 页面没写的字段一律留空，不推不断言。

用法：
    python3 work/extract_fields.py --limit 50          # 试点
    python3 work/extract_fields.py                     # 全量
输出：work/fields.jsonl（每家公司一行，含证据）
"""

import argparse
import html as htmllib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar_extract import (  # noqa: E402
    extract_all,
    extract_batches,
    extract_cities,
    extract_directions,
    extract_grad_years,
    extract_windows_multi,
    merge_windows,
    strip_tags,
)

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

GAP = 1.0
_lock = threading.Lock()
_host_at: dict[str, float] = {}

BLOCK_MARK = re.compile(r"验证码|滑块|安全验证|人机验证|captcha|请先登录|登录后查看|访问受限|"
                        r"Just a moment|cf-chl|enable JavaScript and cookies", re.I)

# 公告/简章类链接的特征词（用于 P3 下钻）
ANNOUNCE = re.compile(r"公告|简章|通知|动态|新闻|启动|详情|说明|须知|guide|notice|news|announce|"
                      r"campus|recruit|zhaopin|xz|gg", re.I)


def throttle(host: str) -> None:
    with _lock:
        now = time.monotonic()
        at = max(now, _host_at.get(host, 0.0) + GAP)
        _host_at[host] = at
    if at > now:
        time.sleep(at - now)


def fetch(client: httpx.Client, url: str, *, timeout: float = 15.0) -> dict:
    """GET 一个页面；返回 html/status/final/blocked。同主机限速。"""
    h = (urlsplit(url).hostname or "").lower()
    throttle(h)
    try:
        r = client.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"},
                       follow_redirects=True, timeout=timeout)
    except Exception as e:
        return {"url": url, "status": None, "html": "", "err": type(e).__name__, "blocked": False}
    blocked = r.status_code in (401, 403, 412) or bool(BLOCK_MARK.search(r.text[:4000]))
    return {"url": str(r.url), "status": r.status_code,
            "html": r.text if r.status_code == 200 else "", "blocked": blocked}


# ---------- P1：ATS 结构化列表 ----------

def beisen_jobs(tenant: str, portal_id: str = "") -> list[dict]:
    """北森新 API。PortalId 必须为空串，否则 0 条。"""
    out = []
    with httpx.Client(timeout=20, headers={"User-Agent": UA}, follow_redirects=False) as c:
        for page in range(4):
            throttle(f"{tenant}.zhiye.com")
            try:
                r = c.post(f"https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList",
                           json={"PageIndex": page, "PageSize": 100, "KeyWords": "",
                                 "SpecialType": 0, "PortalId": portal_id},
                           headers={"Content-Type": "application/json"})
                if r.status_code != 200:
                    break
                d = r.json()
            except Exception:
                break
            if d.get("Code") != 200:
                break
            items = d.get("Data") or []
            for it in items:
                out.append({
                    "title": (it.get("JobAdName") or "").strip(),
                    "category_id": it.get("CategoryId"),
                    "duty": (it.get("Duty") or "")[:3000],
                    "require": (it.get("Require") or "")[:3000],
                    "city": it.get("LocNames") or [],
                    "updated": it.get("UpdateDate") or it.get("PublishDate"),
                })
            if len(items) < 100:
                break
    return out


def beisen_legacy_jobs(host: str, portal: str = "Campus") -> list[dict]:
    """北森 legacy 门户：服务端渲染 <tr><td><a href="/zpdetail/{id}">职位名</a>。

    /Campus、/Social、/ 三个入口都试一遍，取第一个有内容的。
    分页：URL 加 ?PageIndex=N&k=，页码上限读「当前第 N / M 页」。
    """
    for entry in (portal, "Campus", "Social", ""):
        path = f"/{entry}" if entry else "/"
        rows, maxpage = [], 1
        with httpx.Client(timeout=20, headers={"User-Agent": UA}, follow_redirects=True) as c:
            for page in range(maxpage):
                if page > 5:
                    break
                throttle(host)
                try:
                    r = c.get(f"https://{host}{path}", params={"PageIndex": page, "k": ""})
                except Exception:
                    break
                if r.status_code != 200:
                    break
                body = r.text
                m = re.search(r"当前第\s*(\d+)\s*/\s*(\d+)\s*页", body)
                if m:
                    maxpage = min(int(m.group(2)), 8)
                got = 0
                for mm in re.finditer(
                        r'<a[^>]+href="(?:https?://[^"]*?)?/(?:zpdetail|job_show|socialzpdetail)'
                        r'/(\d+)[^"]*"[^>]*>(.*?)</a>', body, re.S | re.I):
                    title = strip_tags(mm.group(2)).strip()
                    title = htmllib.unescape(title)
                    if 2 <= len(title) <= 80:
                        rows.append({"title": title, "category_id": None, "duty": "", "require": "",
                                     "city": [], "detail_url": f"https://{host}/zpdetail/{mm.group(1)}"})
                        got += 1
                if got == 0:
                    break
        if rows:
            return rows
    return []


def beisen_detail(host: str, url: str) -> dict:
    """北森职位详情页：抽工作地点 / 工作职责正文（用于补城市与方向）。"""
    with httpx.Client(timeout=20, headers={"User-Agent": UA}, follow_redirects=True) as c:
        throttle(host)
        try:
            r = c.get(url)
        except Exception:
            return {}
        if r.status_code != 200:
            return {}
        text = strip_tags(r.text)
        return {"text": text[:6000]}


def hotjob_jobs(host: str, tenant: str) -> list[dict]:
    """大易：listPosition 接口（POST 表单），recruitType 1=社招 2=校招 3=实习。"""
    out = []
    with httpx.Client(timeout=20, headers={"User-Agent": UA}) as c:
        for rtype in (2, 3, 1):
            for page in range(3):
                throttle(host)
                try:
                    r = c.post(f"https://{host}/wecruit/positionInfo/listPosition/{tenant}",
                               data={"iSaJAx": "isAjax", "isFrompb": "true", "recruitType": str(rtype),
                                     "pageSize": "100", "currentPage": str(page)},
                               headers={"Content-Type": "application/x-www-form-urlencoded",
                                        "X-Requested-With": "XMLHttpRequest"})
                    d = r.json()
                except Exception:
                    break
                items = d.get("data") or d.get("rows") or []
                if isinstance(items, dict):
                    items = items.get("list") or items.get("records") or []
                if not isinstance(items, list):
                    break
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    out.append({"title": str(it.get("postName") or it.get("name") or "").strip(),
                                "city": [it.get("workPlace") or it.get("city") or ""],
                                "recruit_type": rtype, "company": it.get("company")})
                if len(items) < 100:
                    break
    return out


# ---------- 页面渲染兜底 ----------

def html_info(client: httpx.Client, url: str) -> dict:
    r = fetch(client, url)
    if not r.get("html"):
        return {**r, "text": "", "links": []}
    text = strip_tags(r["html"])
    links, seen = [], set()
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r["html"], re.S | re.I):
        href, label = m.group(1), strip_tags(m.group(2))[:50]
        if ANNOUNCE.search(label + href):
            u = urljoin(r["url"], href).split("#")[0]
            if u in seen:
                continue
            seen.add(u)
            if urlsplit(u).hostname:
                links.append((u, label))
    return {**r, "text": text, "links": links[:12]}


def work(item: dict) -> dict:
    company, sector, url = item["company"], item["sector"], item["url"]
    host = (urlsplit(url).hostname or "").lower()
    kind = "ats-beisen" if host.endswith("zhiye.com") else (
        "ats-hotjob" if "hotjob.cn" in host else "site")
    rec = {"company": company, "sector": sector, "url": url, "host": host, "kind": kind,
           "grad_years": [], "apply_start": None, "apply_end": None, "publish_at": None,
           "date_evidence": None,
           "cities": [], "tracks": [], "project_types": [], "job_titles": [], "n_jobs": 0,
           "titles_source": None, "blocked": False, "evidence": {}, "errors": [], "pages": []}

    try:
        with httpx.Client(follow_redirects=True, timeout=15, headers={"User-Agent": UA}) as client:
            titles, job_extra = [], []
            # ---- P1
            if kind == "ats-beisen":
                tenant = host.split(".")[0]
                jobs = beisen_jobs(tenant, "")
                if jobs:
                    rec["titles_source"] = f"beisen_api:{tenant}"
                else:
                    jobs = beisen_legacy_jobs(host)
                    if jobs:
                        rec["titles_source"] = f"beisen_legacy:{tenant}"
                titles = [j["title"] for j in jobs if j.get("title")]
                if titles:
                    cities = [c for j in jobs for c in (j.get("city") or []) if c]
                    if cities:
                        rec["evidence"]["cities_from_list"] = list(dict.fromkeys(cities))[:20]
                    # legacy 没有城市字段：抓前 3 条详情页补城市
                    if not cities:
                        for j in jobs[:3]:
                            if j.get("detail_url"):
                                d = beisen_detail(host, j["detail_url"])
                                if d.get("text"):
                                    job_extra.append(d["text"])
            elif kind == "ats-hotjob":
                tenant = ""
                m = re.search(r"(SU[0-9a-f]{20,})", url)
                if m:
                    tenant = m.group(1)
                else:
                    try:
                        throttle(host)
                        rr = client.post(f"https://{host}/wecruit/common/getSLD", data={"sld": host},
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
                        ld = (rr.json().get("data") or {}).get("linkData") or {}
                        mm = re.search(r"/(SU[0-9a-f]{20,})/", ld.get("link") or "")
                        tenant = mm.group(1) if mm else ""
                    except Exception:
                        tenant = ""
                if tenant:
                    jobs = hotjob_jobs(host, tenant)
                    titles = [j["title"] for j in jobs if j.get("title")]
                    if titles:
                        rec["titles_source"] = f"hotjob:{host}:{tenant}"
                        cities = [c for j in jobs for c in (j.get("city") or []) if c]
                        if cities:
                            rec["evidence"]["cities_from_list"] = list(dict.fromkeys(cities))[:20]

            # ---- P2：入口页 + 校园/公告页（最多 3 个页面）
            pages = []
            main = html_info(client, url)
            if main.get("blocked"):
                rec["blocked"] = True
            pages.append(main)
            for u, label in (main.get("links") or [])[:3]:
                if len(pages) >= 4:
                    break
                if any(u == p.get("url") for p in pages):
                    continue
                sub = html_info(client, u)
                sub["label"] = label
                pages.append(sub)

            # ---- P3：从公告页再下钻一层拿详情（最多 2 个，只取公告类）
            extra_urls = []
            for p in pages[1:]:
                for u, label in (p.get("links") or []):
                    if re.search(r"公告|简章|通知|详情|启动|说明", label, re.I) and u not in extra_urls:
                        extra_urls.append(u)
            for u in extra_urls[:2]:
                if any(u == p.get("url") for p in pages):
                    continue
                sub = html_info(client, u)
                sub["label"] = "detail"
                pages.append(sub)

            rec["pages"] = [{"url": p.get("url"), "status": p.get("status"),
                             "len": len(p.get("text") or ""), "label": p.get("label")}
                            for p in pages]

            # ---- 合并
            grads, cities, tracks, ptypes, windows = [], [], [], [], []
            for p in pages:
                t = p.get("text") or ""
                if not t:
                    continue
                grads += extract_grad_years(t)
                res = extract_all(p.get("html") or "", p.get("url") or "")
                cities += res["cities"]
                tracks += res["tracks"]
                ptypes += extract_batches(t)
                for w in extract_windows_multi(t):
                    w["page"] = p.get("url")
                    windows.append(w)
            for t in job_extra:
                cities += extract_cities(t)
                tracks += extract_directions(t)
                grads += extract_grad_years(t)

            if windows:
                mw = merge_windows(windows)
                rec["apply_start"] = mw["start"]
                rec["apply_end"] = mw["end"]
                rec["date_evidence"] = mw["evidence"]
                rec["evidence"]["window_page"] = next(
                    (w["page"] for w in windows if w.get("evidence") == mw["evidence"]), None)

            # 职位名也参与届次/方向/城市抽取（这是最硬的证据）
            blob_titles = " ".join(titles[:400])
            if blob_titles:
                grads += extract_grad_years(blob_titles)
                tr = extract_directions(blob_titles)
                for x in tr:
                    for y in tracks:
                        if y["direction"] == x["direction"]:
                            y["roles"] = list(dict.fromkeys(y["roles"] + x["roles"]))[:8]
                            break
                    else:
                        tracks.append(x)
                ptypes += extract_batches(blob_titles)
                cities += extract_cities(blob_titles)
            if titles:
                rec["job_titles"] = titles[:60]
                rec["n_jobs"] = len(titles)
            cities += rec["evidence"].get("cities_from_list", [])

            from collections import Counter
            rec["grad_years"] = [y for y, _ in Counter(grads).most_common(3)]
            rec["cities"] = list(dict.fromkeys([c for c in cities if c]))[:14]
            seen = {}
            for t in tracks:
                seen.setdefault(t["direction"], {"direction": t["direction"], "roles": []})
                seen[t["direction"]]["roles"] = list(dict.fromkeys(
                    seen[t["direction"]]["roles"] + t["roles"]))[:8]
            rec["tracks"] = [v for v in seen.values() if v["roles"]][:6]
            rec["project_types"] = list(dict.fromkeys(ptypes))
    except Exception as e:
        rec["errors"].append(f"{type(e).__name__}: {str(e)[:120]}")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--src", default="work/entry_usable.jsonl")
    ap.add_argument("--out", default="work/fields.jsonl")
    args = ap.parse_args()

    rows = [json.loads(s) for s in (ROOT / args.src).read_text(encoding="utf-8").splitlines() if s.strip()]
    outfile = ROOT / args.out
    done = set()
    if outfile.exists():
        done = {json.loads(s)["company"] for s in outfile.read_text(encoding="utf-8").splitlines() if s.strip()}
    todo = [r for r in rows if r["company"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"total={len(rows)} done={len(done)} todo={len(todo)}", file=sys.stderr)

    n, t0 = 0, time.time()
    with open(outfile, "a", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as ex:
        for rec in ex.map(work, todo):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 20 == 0:
                rate = n / max(time.time() - t0, 1) * 60
                print(f"[{n}/{len(todo)}] {rate:.1f} 家/分", file=sys.stderr)
    print(f"done {n} in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
