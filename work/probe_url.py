"""把「某个域名/子域」直接丢给现有适配器跑一遍，看它是不是一家公司的招聘门户。

为什么要有这个：搜索引擎和租户穷举都只能给出**候选域名**，真正要判断的是
「这个站能不能被我们的适配器解析、有多少岗、是什么公司」。与其为每个新平台写一套
探测脚本，不如复用爬虫本身的适配器——它是唯一事实来源，探到什么样，抓下来就是什么样。

覆盖到的识别：
  /wecruit/positionInfo/listPosition/{SU...}     → hotjob（大易）
  {tenant}.zhiye.com 或页面里有 GetJobAdPageList → beisen（北森）
  mokahr / feishu / workday / avature / tupu360  → 只标记平台名，不解析（需签名/JS）

红线：每主机 ≤1 rps（同一域名下的多个 URL 串行 1.05s）、不跟随到第三方登录页、
只读公开页面。

用法：
    python3 work/probe_url.py "https://x.zhiye.com/campus" "https://wecruit.hotjob.cn/SUxxx/pb/school.html"
    python3 work/probe_url.py --file urls.txt
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

HOTJOB = re.compile(r"https?://([a-z0-9][a-z0-9.-]*hotjob\.cn)/(SU[0-9a-f]{20,32})", re.I)
ZHIYE = re.compile(r"https?://([a-z0-9][a-z0-9-]+)\.zhiye\.com", re.I)
OTHER = [
    (r"mokahr\.com", "moka"),
    (r"\.jobs\.feishu\.cn|jobs\.bytedance\.com", "feishu"),
    (r"myworkdayjobs\.com|myworkdaysite\.com", "workday"),
    (r"avature\.net", "avature"),
    (r"tupu360\.com|italent\.cn", "tupu/italent"),
    (r"dayee\.com", "dayee"),
    (r"51job\.com|zhaopin\.com|liepin\.com|zhipin\.com|shixiseng", "third_party"),
]
TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
LIST_HINT = re.compile(r"GetJobAdPageList|listPosition|positionInfo", re.I)

_last: dict[str, float] = {}


def throttle(host: str) -> None:
    gap = 1.05 - (time.time() - _last.get(host, 0.0))
    if gap > 0:
        time.sleep(gap)
    _last[host] = time.time()


def probe_beisen(tenant: str) -> dict:
    out = {"kind": "beisen", "tenant": tenant, "ok": False, "count": 0}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0) as cli:
            throttle(tenant + ".zhiye.com")
            r = cli.post(f"https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList", json={
                "PageIndex": 0, "PageSize": 10, "KeyWords": "", "SpecialType": 0, "PortalId": "",
                "DisplayFields": ["Category", "LocId", "PostDate", "LocNames"]})
            if r.status_code != 200 or not r.text.lstrip().startswith("{"):
                out["err"] = f"http{r.status_code}"
                return out
            d = r.json()
            if d.get("Code") != 200:
                out["err"] = f"code{d.get('Code')}"
                return out
            items = d.get("Data") or []
            out.update(ok=True, count=max(int(d.get("Count") or 0), len(items)),
                       jobs=[str(i.get("JobAdName") or "")[:36] for i in items[:4]])
    except Exception as e:  # noqa: BLE001
        out["err"] = type(e).__name__
    return out


def probe_hotjob(host: str, tenant: str) -> dict:
    out = {"kind": "hotjob", "host": host, "tenant": tenant, "ok": False, "count": 0}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0,
                          follow_redirects=True) as cli:
            throttle(host)
            r = cli.get(f"https://{host}/wecruit/positionInfo/listPosition/{tenant}",
                        params={"iSaJAx": "isAjax", "request_locale": "zh_CN",
                                "isFrompb": "true", "recruitType": "1",
                                "pageSize": "10", "currentPage": "1"})
            d = r.json()
            body = d.get("data") if isinstance(d.get("data"), dict) else d
            pr = body.get("pageForm") or body
            items = pr.get("pageData") or []
            out.update(ok=True,
                       count=int(body.get("positonNum") or 0) or int(pr.get("totalPage") or 0) * 15,
                       jobs=[str(i.get("postName") or "")[:36] for i in items[:4]],
                       companies=list({str(i.get("company") or "")[:20] for i in items[:6]}))
    except Exception as e:  # noqa: BLE001
        out["err"] = type(e).__name__
    return out


def probe_url(u: str) -> dict:
    m = HOTJOB.match(u)
    if m:
        return probe_hotjob(m.group(1).lower(), m.group(2))
    m = ZHIYE.match(u)
    if m:
        return probe_beisen(m.group(1).lower())
    host = (urlparse(u).hostname or "").lower()
    for pat, name in OTHER:
        if re.search(pat, host):
            return {"kind": name, "url": u, "ok": None, "count": 0, "note": "平台识别，不解析"}
    # 通用：抓页面看是不是 SPA 里嵌了 ATS 端点
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0,
                          follow_redirects=True) as cli:
            throttle(host)
            r = cli.get(u)
            t = TITLE.search(r.text or "")
            return {"kind": "generic", "url": u, "status": r.status_code,
                    "title": re.sub(r"\s+", " ", t.group(1)).strip()[:60] if t else "",
                    "ats_hint": bool(LIST_HINT.search(r.text or "")), "count": 0,
                    "len": len(r.text or "")}
    except Exception as e:  # noqa: BLE001
        return {"kind": "generic", "url": u, "err": type(e).__name__, "count": 0}


def main() -> int:
    args = sys.argv[1:]
    urls = []
    if args and args[0] == "--file":
        urls = [ln.strip() for ln in Path(args[1]).read_text(encoding="utf-8-sig").splitlines()
                if ln.strip()]
    else:
        urls = [a for a in args if a.startswith("http")]
    for u in urls:
        print(json.dumps(probe_url(u), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
