"""批量验证北森 zhiye.com 租户：门户代际（新版 JSON 接口 / 旧版服务端渲染）、岗位数、页面标题。
每个租户 2 个请求，间隔 1.5s。输出 TSV（以 VERIFY 开头，便于在 CI 日志里过滤）。

用法：python scripts/verify_beisen_tenants.py docs/recon/beisen_tenants.txt
"""

import re
import sys
import time

import httpx

UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; tenant verification)"
API = "https://{t}.zhiye.com/api/Jobad/GetJobAdPageList"
PAGE = "https://{t}.zhiye.com/campus/jobs"


def verify(client: httpx.Client, t: str) -> tuple[str, str, str]:
    title = "-"
    try:
        p = client.get(PAGE.format(t=t))
        m = re.search(r"<title>(.*?)</title>", p.text, re.S | re.I)
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:60] if m else "-"
    except httpx.HTTPError as e:
        return "error", type(e).__name__, title
    time.sleep(1.5)
    try:
        r = client.post(API.format(t=t), json={"PageIndex": 0, "PageSize": 1, "KeyWords": "",
                                               "SpecialType": 0, "PortalId": ""})
    except httpx.HTTPError as e:
        return "error", type(e).__name__, title
    if "json" in r.headers.get("content-type", ""):
        d = r.json()
        return ("new" if d.get("Code") == 200 else f"code{d.get('Code')}"), str(d.get("Count")), title
    return ("legacy" if "404" in str(r.url) else f"http{r.status_code}"), "-", title


def main(path: str) -> int:
    tenants = [ln.split("#")[0].strip() for ln in open(path, encoding="utf-8")]
    tenants = [t for t in dict.fromkeys(tenants) if t]
    with httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True) as client:
        for t in tenants:
            kind, count, title = verify(client, t)
            print(f"VERIFY\t{t}\t{kind}\t{count}\t{title}", flush=True)
            time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
