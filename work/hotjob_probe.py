"""探测大易门户（新版 wecruit），返回校招/社招岗位数。只读公开 JSON，1 req/s。"""
import json
import sys
import time

import httpx

UA = "jobradar/0.1 (+https://github.com/jobradar/job_radar)"
_last = {}


def throttle(host):
    gap = time.time() - _last.get(host, 0)
    if gap < 1.0:
        time.sleep(1.0 - gap)
    _last[host] = time.time()


def probe(tenant, host="wecruit.hotjob.cn"):
    out = {}
    with httpx.Client(headers={"User-Agent": UA}, timeout=25, follow_redirects=True) as c:
        for code, name in (("1", "campus"), ("2", "social")):
            url = f"https://{host}/wecruit/positionInfo/listPosition/{tenant}"
            params = {"iSaJAx": "isAjax", "request_locale": "zh_CN", "isFrompb": "true",
                      "recruitType": code, "pageSize": "50", "currentPage": "1"}
            throttle(host)
            try:
                r = c.get(url, params=params, headers={
                    "Referer": f"https://{host}/{tenant}/pb/social.html"})
                d = r.json()
            except Exception as e:  # noqa: BLE001
                out[name] = f"ERR {type(e).__name__} {r.text[:60] if 'r' in dir() else ''}"
                continue
            posts = d.get("positionList") or d.get("postList") or []
            out[name] = (d.get("positonNum") or d.get("positionNum") or d.get("total") or 0, len(posts))
            if posts:
                p0 = posts[0]
                out[name + "_first"] = p0.get("postName")
                out[name + "_co"] = p0.get("company") or p0.get("orgName")
    return out


if __name__ == "__main__":
    tenant = sys.argv[1]
    host = sys.argv[2] if len(sys.argv) > 2 else "wecruit.hotjob.cn"
    print(json.dumps(probe(tenant, host), ensure_ascii=False))
