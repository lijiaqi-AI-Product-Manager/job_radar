"""探应届生 www 侧服务端渲染页：/deadline/、/industry/、详情页。输出 work/_yjs2.txt。"""
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
OUT = Path("work/_yjs2.txt")


def strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


rows = []
urls = [
    ("deadline", "https://www.yingjiesheng.com/deadline/"),
    ("industry", "https://www.yingjiesheng.com/industry/"),
    ("major", "https://www.yingjiesheng.com/major/"),
    ("xuanjianghui", "https://my.yingjiesheng.com/xuanjianghui.html"),
]
with httpx.Client(timeout=18.0, headers=H, follow_redirects=True, verify=False) as c:
    for name, url in urls:
        rec = {"name": name, "url": url}
        try:
            r = c.get(url)
            b = r.text
            rec["status"] = r.status_code
            rec["bytes"] = len(b)
            rec["title"] = (re.search(r"<title[^>]*>(.*?)</title>", b, re.S) or [None, ""])[1].strip()[:60]
            rec["n_links"] = len(re.findall(r"<a ", b))
            rec["links"] = [[strip(t)[:40], h[:110]] for h, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.S) if len(strip(t)) > 4][:25]
            Path(f"work/_yjs_{name}.html").write_text(b, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(rec)
OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
