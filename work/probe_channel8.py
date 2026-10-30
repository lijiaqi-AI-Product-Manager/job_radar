"""抽南开招聘信息列表条目 + 一条详情页结构。输出 work/_chan8.txt。"""
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
OUT = Path("work/_chan8.txt")


def strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


rows = []
with httpx.Client(timeout=15.0, headers=H, follow_redirects=True, verify=False) as c:
    b = c.get("https://career.nankai.edu.cn/correcruit/index.html").text
    # 列表条目：<a href="/correcruit/content/id/123.html">标题</a> 或带 li
    pats = [
        r'href="(/correcruit/content/id/\d+\.html)"[^>]*>(.*?)</a>',
        r'href="(/recruitment/content/type/\d+/id/\d+\.html)"[^>]*>(.*?)</a>',
        r'href="([^"]*content[^"]*id/\d+[^"]*)"[^>]*>(.*?)</a>',
    ]
    found = []
    for p in pats:
        found += [(h, strip(t)) for h, t in re.findall(p, b, re.S)]
    # 去重
    seen, items = set(), []
    for h, t in found:
        if h in seen:
            continue
        seen.add(h)
        items.append([t[:60], h])
    rows.append({"page": "correcruit", "items": items[:20], "n": len(items)})

    # 详情页
    if items:
        u = "https://career.nankai.edu.cn" + items[0][1]
        r = c.get(u)
        d = r.text
        rows.append(
            {
                "detail_url": u,
                "status": r.status_code,
                "bytes": len(d),
                "title": (re.search(r"<title[^>]*>(.*?)</title>", d, re.S) or [None, ""])[1].strip()[:80],
                "has_position_words": [w for w in ("岗位", "职责", "任职要求", "招聘人数", "薪资", "专业") if w in d],
                "text_len": len(strip(re.sub(r"<script.*?</script>", "", d, flags=re.S))),
                "text_head": strip(re.sub(r"<script.*?</script>", "", d, flags=re.S))[:600],
                "apply_links": sorted(set(re.findall(r'https?://[^"\s<>]*(?:zhiye|hotjob|feishu|mokahr|careers|job)[^"\s<>]*', d)))[:6],
            }
        )
    # 招聘会列表
    b2 = c.get("https://career.nankai.edu.cn/recruitment/index.html").text
    found2 = re.findall(r'href="([^"]*content[^"]*id/\d+[^"]*)"[^>]*>(.*?)</a>', b2, re.S)
    seen2, items2 = set(), []
    for h, t in found2:
        t = strip(t)
        if h in seen2 or not t:
            continue
        seen2.add(h)
        items2.append([t[:60], h])
    rows.append({"page": "recruitment", "items": items2[:20], "n": len(items2)})
OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
