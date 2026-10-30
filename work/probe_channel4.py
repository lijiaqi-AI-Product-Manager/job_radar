"""探第四条规模化渠道：职友集(jobui)、猎聘企业页、高校就业网。

只做只读探测：robots + 首屏 HTML 体积 + 关键结构是否存在。
结果写 work/_chan5.txt（UTF-8），控制台不打印中文。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

OUT = Path("work/_chan5.txt")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

TARGETS = {
    "jobui_robots": "https://www.jobui.com/robots.txt",
    "jobui_search": "https://www.jobui.com/cmp?keyword=%E4%B8%AD%E5%8E%9F%E9%93%B6%E8%A1%8C",
    "liepin_robots": "https://www.liepin.com/robots.txt",
    "liepin_company": "https://www.liepin.com/company/?keyword=%E4%B8%AD%E5%8E%9F%E9%93%B6%E8%A1%8C",
    "nankai_home": "https://career.nankai.edu.cn/",
    "sdu_home": "https://job.sdu.edu.cn/",
    "zju_home": "https://career.zju.edu.cn/",
    "ustc_home": "https://job.ustc.edu.cn/",
    "whu_home": "https://job.whu.edu.cn/",
    "xjtlu_home": "https://careers.xjtlu.edu.cn/",
}


def probe(name: str, url: str, client: httpx.Client) -> dict:
    rec: dict = {"name": name, "url": url}
    try:
        r = client.get(url, follow_redirects=True)
        body = r.text
        rec["status"] = r.status_code
        rec["bytes"] = len(body)
        rec["final"] = str(r.url)
        rec["title"] = (re.search(r"<title[^>]*>(.*?)</title>", body, re.S) or [None, ""])[1].strip()[:80]
        if name.endswith("_robots"):
            rec["disallow"] = [ln.strip() for ln in body.splitlines() if ln.strip().lower().startswith("disallow")][:20]
            rec["crawl_delay"] = [ln.strip() for ln in body.splitlines() if "crawl-delay" in ln.lower()][:3]
        else:
            # 结构证据
            rec["ev"] = {
                "list_items": len(re.findall(r"<li[^>]*class=\"[^\"]*(?:job|item|list)[^\"]*\"", body)),
                "job_links": len(re.findall(r"href=\"[^\"]*(?:/job/|/jobs/|/position|/zhaopin/|/jobdetail)", body)),
                "company_links": len(re.findall(r"href=\"[^\"]*/company/", body)),
                "has_next": bool(re.search(r"(下一页|next|page=2)", body)),
                "json_ld": body.count("application/ld+json"),
            }
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def main() -> None:
    rows = []
    with httpx.Client(timeout=12.0, headers=HEADERS, verify=False) as client:
        for name, url in TARGETS.items():
            rows.append(probe(name, url, client))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()
