"""探职友集(jobui)企业岗位页：搜索 -> 公司 id -> 岗位列表是否服务端渲染。

输出 work/_jobui.txt（UTF-8）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

OUT = Path("work/_jobui.txt")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
NAMES = ["中原银行", "海信视像", "远景能源", "中国兵器工业集团"]


def main() -> None:
    rows = []
    with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as c:
        for name in NAMES:
            rec: dict = {"name": name}
            try:
                r = c.get("https://www.jobui.com/cmp", params={"keyword": name})
                rec["search_status"] = r.status_code
                rec["search_bytes"] = len(r.text)
                ids = re.findall(r'href="(/company/(\d+)/)"', r.text)
                rec["company_ids"] = [i for i, _ in ids][:5]
                # 搜索页里通常还有公司名，抽前几个标题
                rec["titles"] = [t.strip()[:40] for t in re.findall(r'<h3[^>]*>(.*?)</h3>', r.text, re.S)[:5]]
                if ids:
                    cid = ids[0][1]
                    time.sleep(1.2)
                    jr = c.get(f"https://www.jobui.com/company/{cid}/jobs/")
                    body = jr.text
                    rec["jobs_status"] = jr.status_code
                    rec["jobs_bytes"] = len(body)
                    rec["jobs_title"] = (re.search(r"<title[^>]*>(.*?)</title>", body, re.S) or [None, ""])[1].strip()[:60]
                    rec["job_links"] = sorted(set(re.findall(r'href="(/jobs/\d+/)"', body)))[:5]
                    rec["job_blocks"] = len(re.findall(r'class="[^"]*job-item', body))
                    rec["has_jd_text"] = ("岗位职责" in body) or ("任职要求" in body)
                    m = re.search(r'共\s*(\d+)\s*个职位', body)
                    rec["job_count_text"] = m.group(1) if m else None
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(rec)
            time.sleep(1.5)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()
