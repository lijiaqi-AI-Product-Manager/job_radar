"""抽应届生 /deadline/fulltime/ 分类页条目结构。输出 work/_yjs3.txt。"""
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


def strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


URL = "https://www.yingjiesheng.com/deadline/fulltime/index_13_1.html"
rows = []
with httpx.Client(timeout=18.0, headers=H, follow_redirects=True, verify=False) as c:
    r = c.get(URL)
    b = r.text
    Path("work/_yjs_deadline13.html").write_text(b, encoding="utf-8")
    rows.append({"url": URL, "status": r.status_code, "bytes": len(b)})
    # 找表格行
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", b, re.S)
    rows.append({"n_tr": len(trs)})
    out = []
    for tr in trs[:20]:
        links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', tr, re.S)
        txt = strip(tr)
        if txt:
            out.append({"text": txt[:120], "links": [[strip(t)[:40], h[:90]] for h, t in links]})
    rows.append({"rows": out})
Path("work/_yjs3.txt").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
