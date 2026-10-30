"""探南开就业网招聘信息列表 + 应届生首页结构。输出 work/_chan7.txt。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
OUT = Path("work/_chan7.txt")


def strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


rows = []
with httpx.Client(timeout=15.0, headers=H, follow_redirects=True, verify=False) as c:
    # 南开招聘信息列表
    for url in [
        "https://career.nankai.edu.cn/correcruit/index.html",
        "https://career.nankai.edu.cn/recruitment/index.html",
    ]:
        r = c.get(url)
        b = r.text
        items = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        rows.append(
            {
                "url": url,
                "status": r.status_code,
                "bytes": len(b),
                "title": (re.search(r"<title[^>]*>(.*?)</title>", b, re.S) or [None, ""])[1].strip()[:60],
                "n_links": len(items),
                "sample": [[strip(t)[:40], h] for h, t in items if strip(t) and "/" in h][:15],
                "has_next": bool(re.search("下一页|next|page", b)),
            }
        )
    # 应届生首页链接
    r = c.get("https://www.yingjiesheng.com/")
    b = r.text
    items = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
    rows.append(
        {
            "url": "https://www.yingjiesheng.com/",
            "status": r.status_code,
            "bytes": len(b),
            "n_links": len(items),
            "sample": [[strip(t)[:36], h[:110]] for h, t in items if strip(t)][:25],
        }
    )
OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
