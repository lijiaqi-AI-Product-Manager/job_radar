"""探第四条规模化渠道（第二轮）：政府公共招聘平台、高校就业网、海投网/应届生。

输出 work/_chan6.txt（UTF-8）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

OUT = Path("work/_chan6.txt")
H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def get(c: httpx.Client, url: str) -> tuple[int, str]:
    try:
        r = c.get(url, follow_redirects=True)
        return r.status_code, r.text
    except Exception as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}"


def main() -> None:
    rows: list[dict] = []
    with httpx.Client(timeout=15.0, headers=H, verify=False) as c:
        # 1) 中国公共招聘网
        for name, url in {
            "mohrss_robots": "https://job.mohrss.gov.cn/robots.txt",
            "mohrss_home": "https://job.mohrss.gov.cn/",
            "mohrss_search": "https://job.mohrss.gov.cn/jobsearch/index.jhtml",
        }.items():
            st, body = get(c, url)
            rows.append(
                {
                    "name": name,
                    "status": st,
                    "bytes": len(body),
                    "title": (re.search(r"<title[^>]*>(.*?)</title>", body, re.S) or [None, ""])[1].strip()[:70],
                    "disallow": [ln.strip() for ln in body.splitlines() if ln.lower().startswith("disallow")][:12] if name.endswith("robots") else None,
                    "job_links": len(re.findall(r"/job/\w+", body)) if not name.endswith("robots") else None,
                    "api_hits": sorted(set(re.findall(r"['\"](/[\w/]+\.(?:json|do|action|jhtml))['\"]", body)))[:8] if not name.endswith("robots") else None,
                }
            )
        # 2) 应届生
        for name, url in {
            "yjs_robots": "https://www.yingjiesheng.com/robots.txt",
            "yjs_home": "https://www.yingjiesheng.com/",
            "yjs_qiuzhi": "https://www.yingjiesheng.com/zhaopin/",
        }.items():
            st, body = get(c, url)
            rows.append(
                {
                    "name": name,
                    "status": st,
                    "bytes": len(body),
                    "title": (re.search(r"<title[^>]*>(.*?)</title>", body, re.S) or [None, ""])[1].strip()[:70],
                    "disallow": [ln.strip() for ln in body.splitlines() if ln.lower().startswith("disallow")][:12] if name.endswith("robots") else None,
                    "job_links": len(re.findall(r"/\d{4,}/?", body)) if not name.endswith("robots") else None,
                }
            )
        # 3) 海投网（宣讲会聚合）
        for name, url in {
            "haitou_robots": "https://www.haitou.cc/robots.txt",
            "haitou_home": "https://www.haitou.cc/",
            "haitou_talk": "https://www.haitou.cc/xjh/",
        }.items():
            st, body = get(c, url)
            rows.append(
                {
                    "name": name,
                    "status": st,
                    "bytes": len(body),
                    "title": (re.search(r"<title[^>]*>(.*?)</title>", body, re.S) or [None, ""])[1].strip()[:70],
                    "disallow": [ln.strip() for ln in body.splitlines() if ln.lower().startswith("disallow")][:12] if name.endswith("robots") else None,
                    "talk_items": len(re.findall(r"/xjh/\d+", body)) if not name.endswith("robots") else None,
                }
            )
        # 4) 高校就业网：抓首页里“招聘/职位/宣讲”的导航链接
        for host in ["career.nankai.edu.cn", "job.sdu.edu.cn", "job.ustc.edu.cn", "career.bnu.edu.cn"]:
            st, body = get(c, f"https://{host}/")
            links = []
            for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
                t = re.sub(r"<[^>]+>", "", text).strip()
                if any(k in t for k in ("招聘", "职位", "宣讲", "双选", "岗位")):
                    links.append([t[:20], href[:100]])
            rows.append({"name": f"school_{host}", "status": st, "bytes": len(body), "links": links[:10]})
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()
