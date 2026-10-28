"""Verify candidate tenants discovered by web search (zhiye / hotjob / feishu).

Usage: python work/probe_search_candidates.py tmp_cand.jsonl [out.jsonl]
Input line: {"kind": "beisen|legacy|hotjob|feishu", "key": "<tenant or SU>", "hint": "<company>"}
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from jobradar.adapters.base import make_client
from jobradar.adapters.feishu_atsx import recruit_type_of

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
ZPDETAIL_RE = re.compile(r"/zpdetail/|/job_show/")
SU_RE = re.compile(r"SU[0-9a-fA-F]{20,}")


def _client():
    # 用项目自己的 client：hotjob 的 listPosition 对裸 httpx 会回 405，
    # 必须带 base.py 里那套 UA/Accept 头。
    return make_client()


def beisen(c: httpx.Client, tenant: str) -> dict:
    body = {"PageIndex": 1, "PageSize": 10, "DisplayFields": ["Category", "LocId", "PostDate", "LocNames"]}
    try:
        r = c.post(f"https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList", json=body)
        if r.status_code == 200 and r.text.startswith("{"):
            js = r.json()
            if js.get("Code") == 200:
                return {"ok": True, "kind": "beisen", "count": js.get("Count") or 0}
    except Exception:
        pass
    # fallback: legacy server-rendered campus page
    try:
        r = c.get(f"https://{tenant}.zhiye.com/campus")
        n = len(set(ZPDETAIL_RE.findall(r.text)))
        title = (TITLE_RE.search(r.text).group(1).strip() if TITLE_RE.search(r.text) else "")
        if r.status_code == 200 and n:
            links = len(ZPDETAIL_RE.findall(r.text))
            return {"ok": True, "kind": "legacy", "count": links, "title": title}
    except Exception:
        pass
    return {"ok": False}


def hotjob(c, su: str) -> dict:
    """recruitType 1=校园、3=实习（2 是社招）。翻页数到头为止。

    `pageForm.total` 在很多租户上是 null，不能拿它当岗位数。
    """
    headers = {"Referer": f"https://wecruit.hotjob.cn/{su}/pb/social.html"}
    total = 0
    company = ""
    ok = False
    for code in ("1", "3"):
        for page in (1, 2, 3, 4, 5, 6):
            params = {"iSaJAx": "isAjax", "request_locale": "zh_CN", "isFrompb": "true",
                      "recruitType": code, "pageSize": "50", "currentPage": str(page)}
            try:
                r = c.get(f"https://wecruit.hotjob.cn/wecruit/positionInfo/listPosition/{su}",
                          params=params, headers=headers)
                data = (r.json().get("data") or {})
                items = (data.get("pageForm") or {}).get("pageData") or []
                if items and not company:
                    company = items[0].get("company") or ""
                total += len(items)
                ok = True
                if not items:
                    break
            except Exception:
                break
    if not ok:
        return {"ok": False}
    return {"ok": True, "kind": "hotjob", "count": total, "title": company}


def feishu(c: httpx.Client, slug: str) -> dict:
    """返回校招/实习岗位数：portal_type=3 里按 recruit_type_of 过滤掉纯社招。

    门户的 `count` 是全部岗位（含社招），不能直接当校招数——它石智航 142 条
    全是「社招/全职/外包」，真正入库 0 条。
    """
    base = f"https://{slug}.jobs.feishu.cn"
    try:
        r = c.get(base + "/")
        title = (TITLE_RE.search(r.text).group(1).strip() if TITLE_RE.search(r.text) else "")
        tok = c.post(base + "/api/v1/csrf/token", json={"portal_entrance": 1}).json()
        token = (tok.get("data") or {}).get("token")
        body = {"keyword": "", "limit": 100, "offset": 0, "job_category_id_list": [],
                "location_code_list": [], "portal_type": 3, "portal_entrance": 1, "website_path": "campus"}
        rr = c.post(base + "/api/v1/search/job/posts", json=body,
                    headers={"x-csrf-token": token, "Accept": "application/json"})
        items = ((rr.json().get("data") or {}).get("job_post_list") or []) if rr.status_code == 200 else []
        campus = sum(1 for it in items if recruit_type_of(it) in ("campus", "intern"))
        return {"ok": bool(token), "kind": "feishu", "count": campus, "total": len(items), "title": title}
    except Exception:
        return {"ok": False}


def one(item: dict) -> dict:
    kind, key = item["kind"], item["key"]
    c = _client()
    try:
        if kind == "feishu":
            res = feishu(c, key)
        elif kind == "hotjob":
            res = hotjob(c, key)
        else:
            res = beisen(c, key)
    finally:
        c.close()
    out = {**item, **res}
    if res.get("ok"):
        out["host"] = f"{key}.zhiye.com" if res.get("kind") in ("beisen", "legacy") else key
    return out


def main() -> int:
    src = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("work/search_cand_verified.jsonl")
    items = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(one, items):
            rows.append(r)
            time.sleep(0)  # keep ordering deterministic
    with out_path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ok = [r for r in rows if r.get("ok")]
    print(f"candidates={len(rows)} alive={len(ok)}")
    for r in ok:
        print(f"{r['kind']:8s} {r['key']:32s} count={r.get('count'):5d} {r.get('title','')[:36]} | {r.get('hint','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
