"""批量验证「同款就业网 CMS」候选高校：打 /correcruit/index.html 看能否解析出条目。

判据：200 + parse_list_page 能解析出 ≥10 条（title/company/url 齐全）。
输出 work/_campus_schools.txt
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jobradar.adapters.campus import parse_list_page  # noqa: E402

OUT = ROOT / "work" / "_campus_schools.txt"
H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
HOSTS = [
    "recruit.djtu.edu.cn",
    "recruit.ahjzu.edu.cn",
    "career.hebut.edu.cn",
    "jobs.tiangong.edu.cn",
    "graduate.buct.edu.cn",
    "jy.tust.edu.cn",
    "career.nankai.edu.cn",
]


def main() -> None:
    rows = []
    with httpx.Client(timeout=15.0, headers=H, follow_redirects=True, verify=False) as c:
        for host in HOSTS:
            rec: dict = {"host": host}
            base = f"https://{host}"
            try:
                r = c.get(f"{base}/correcruit/index.html")
                rec["status"] = r.status_code
                rec["bytes"] = len(r.text)
                rec["final"] = str(r.url)
                items = parse_list_page(r.text, base) if r.status_code == 200 else []
                rec["parsed"] = len(items)
                rec["sample"] = [(i["company"], i["title"][:20]) for i in items[:2]]
                rec["next_ok"] = None
                if items:
                    time.sleep(1.0)
                    r2 = c.get(f"{base}/correcruit/index/p/2.html")
                    rec["next_ok"] = r2.status_code == 200 and len(parse_list_page(r2.text, base)) > 0
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(rec)
            time.sleep(1.2)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r["host"] for r in rows if r.get("parsed", 0) >= 10]
    print(f"ok={len(ok)}/{len(rows)}: {','.join(ok)}")


if __name__ == "__main__":
    main()
