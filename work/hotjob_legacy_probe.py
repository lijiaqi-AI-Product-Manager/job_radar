"""探测大易老版 wt 门户：`/wt/{TENANT}/web/json/position/list`，返回各招聘类型岗位数。

租户代码通常是大写（cgn.hotjob.cn 的租户是 `CGN`，不是域名第一段小写）。
用法：python3 work/hotjob_legacy_probe.py CGN cgn.hotjob.cn
"""
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


def probe(tenant, host="www.hotjob.cn"):
    out = {}
    with httpx.Client(headers={"User-Agent": UA}, timeout=25, follow_redirects=True) as c:
        for code, name in (("1", "campus"), ("2", "social"), ("3", "intern")):
            url = f"https://{host}/wt/{tenant}/web/json/position/list"
            params = {"recruitType": code, "page": "1", "brandCode": "1",
                      "lanType": "1", "trademark": "1", "rowSize": "10"}
            throttle(host)
            try:
                r = c.get(url, params=params, headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"https://{host}/wt/{tenant}/web/index"})
                d = json.loads(r.text)
            except Exception as e:  # noqa: BLE001
                out[name] = f"ERR {type(e).__name__} {r.text[:40]}"
                continue
            posts = d.get("postList") or []
            out[name] = (int(d.get("rowCount") or 0), int(d.get("pageCount") or 0))
            if posts:
                p0 = posts[0]
                out[name + "_first"] = p0.get("postName")
                out[name + "_place"] = p0.get("workPlace")
                out[name + "_jd"] = len(p0.get("workContent") or "")
    return out


if __name__ == "__main__":
    tenant = sys.argv[1]
    host = sys.argv[2] if len(sys.argv) > 2 else "www.hotjob.cn"
    print(tenant, host, json.dumps(probe(tenant, host), ensure_ascii=False))
