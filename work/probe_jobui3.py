"""判定职友集(jobui)是否可作为岗位渠道：搜索参数有效性 + 企业页岗位块。"""
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

CIDS = {
    "海信视像": "16694857",
    "远景能源": "13374285",
    "中国兵器工业集团": "16831669",
    "小米": None,
    "恒瑞医药": None,
}

rows = []
with httpx.Client(timeout=20.0, headers=H, follow_redirects=True, verify=False) as c:
    # 1) 搜索参数对比
    probes = [
        ("kw_bank", "https://www.jobui.com/jobs/?jobKw=%E9%93%B6%E8%A1%8C"),
        ("kw_java", "https://www.jobui.com/jobs/?jobKw=java"),
        ("kw2", "https://www.jobui.com/jobs?jobKw=%E9%93%B6%E8%A1%8C"),
        ("search", "https://www.jobui.com/jobs/search/?jobKw=%E9%93%B6%E8%A1%8C"),
    ]
    for name, url in probes:
        r = c.get(url)
        b = r.text
        rows.append(
            {
                "probe": name,
                "status": r.status_code,
                "bytes": len(b),
                "title": (re.search(r"<title[^>]*>(.*?)</title>", b, re.S) or [None, ""])[1].strip()[:50],
                "job_href": len(re.findall(r'href="(/jobs/[^"]+)"', b)),
                "n_company_links": len(re.findall(r'href="/company/', b)),
            }
        )
    # 2) 企业页岗位
    for name, cid in CIDS.items():
        if not cid:
            r = c.get("https://www.jobui.com/cmp", params={"keyword": name})
            m = re.search(r'href="/company/(\d+)/"', r.text)
            cid = m.group(1) if m else None
        if not cid:
            rows.append({"company": name, "error": "no cid"})
            continue
        r = c.get(f"https://www.jobui.com/company/{cid}/jobs/")
        b = r.text
        rows.append(
            {
                "company": name,
                "cid": cid,
                "status": r.status_code,
                "bytes": len(b),
                "no_jobs_text": "暂无招聘职位" in b or "暂无" in b,
                "job_href": len(re.findall(r'href="(/jobs/[^"]+)"', b)),
                "class_job": len(re.findall(r'class="[^"]*job[^"]*"', b)),
            }
        )
Path("work/_jobui3.txt").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
