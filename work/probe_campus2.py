"""探第二种高校就业网 CMS（/campus/view/id/{id} 家族：郑州大学、上海电力、中国石油大学…）。

找列表页 + 抽条目骨架，输出 work/_campus2.txt
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}
HOSTS = ["job.zzu.edu.cn", "career.shiep.edu.cn", "career.cup.edu.cn", "job.xasyxy.com"]
CAND_LIST = ["/campus", "/campus/index", "/campus/list", "/campus/view", "/correcruit/index.html"]
lines = []
rows = []
with httpx.Client(timeout=15.0, headers=H, follow_redirects=True, verify=False) as c:
    for host in HOSTS:
        rec: dict = {"host": host}
        try:
            home = c.get(f"https://{host}/")
            b = home.text
            rec["home"] = [home.status_code, len(b)]
            # 从首页找「招聘公告/招聘信息」入口
            nav = []
            for href, anchor in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', b, re.S):
                t = re.sub(r"<[^>]+>|\s+", "", anchor)
                if t in {"招聘公告", "招聘信息", "校园招聘", "招聘会", "招聘岗位"}:
                    nav.append({"text": t, "href": href})
            rec["nav"] = nav[:6]
            tested = []
            for path in CAND_LIST:
                try:
                    r = c.get(f"https://{host}{path}")
                    txt = r.text
                    n = len(re.findall(r"/campus/view/id/\d+", txt))
                    tested.append({"path": path, "status": r.status_code, "bytes": len(txt), "view_links": n})
                except Exception as exc:  # noqa: BLE001
                    tested.append({"path": path, "error": type(exc).__name__})
            rec["paths"] = tested
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(rec)
        lines.append(json.dumps(rec, ensure_ascii=False))
Path("work/_campus2.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines)[:3000])
