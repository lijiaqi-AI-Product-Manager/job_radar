"""探应届生 q.yingjiesheng.com 搜索接口与列表渲染方式。输出 work/_yjs.txt。"""
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
OUT = Path("work/_yjs.txt")


def strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


rows = []
urls = [
    ("search_kw", "https://q.yingjiesheng.com/jobs/search/?keyword=%E4%B8%AD%E5%8E%9F%E9%93%B6%E8%A1%8C"),
    ("search_jobkey", "https://q.yingjiesheng.com/jobs/search/?jobkey=%E4%B8%AD%E5%8E%9F%E9%93%B6%E8%A1%8C"),
    ("search_plain", "https://q.yingjiesheng.com/jobs/search/?jobarea=050000"),
    ("home_q", "https://q.yingjiesheng.com/"),
]
with httpx.Client(timeout=15.0, headers=H, follow_redirects=True, verify=False) as c:
    for name, url in urls:
        rec = {"name": name, "url": url}
        try:
            r = c.get(url)
            b = r.text
            rec["status"] = r.status_code
            rec["bytes"] = len(b)
            rec["title"] = (re.search(r"<title[^>]*>(.*?)</title>", b, re.S) or [None, ""])[1].strip()[:60]
            rec["has_company"] = "中原银行" in b
            rec["n_job_links"] = len(re.findall(r"/job/[a-z0-9]+\.html", b))
            rec["n_any_links"] = len(re.findall(r"<a ", b))
            rec["api"] = sorted(set(re.findall(r"['\"](/[a-z/]+(?:search|list|jobs)[a-z/]*)['\"]", b)))[:6]
            rec["sample"] = [[strip(t)[:36], h[:90]] for h, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.S) if len(strip(t)) > 6][:12]
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(rec)
OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
