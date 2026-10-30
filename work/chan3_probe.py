"""探测牛客/智联校招的「按公司查岗位」页面结构，输出 work/_chan3.json。"""

import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

URLS = {
    "nc_job_detail": "https://www.nowcoder.com/jobs/hr/98683",
    "nc_company_21369": "https://www.nowcoder.com/company/21369",
    "nc_school_jobs": "https://www.nowcoder.com/jobs/school/jobs",
    "xy_home": "https://xiaoyuan.zhaopin.com/",
}


def main() -> None:
    out: dict[str, object] = {}
    with httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": UA}) as c:
        for k, u in URLS.items():
            try:
                r = c.get(u)
                t = r.text
                item = {
                    "status": r.status_code,
                    "final": str(r.url),
                    "len": len(t),
                    "initial_state": t.find("__INITIAL_STATE__"),
                    "links_company": sorted(set(re.findall(r'href="(/company/[^"]+|/jobs/hr/\d+)"', t)))[:10],
                    "h3": re.findall(r"<h3[^>]*>(.*?)</h3>", t, re.S)[:6],
                    "api": sorted(set(re.findall(r'"(/api/[a-zA-Z0-9/_{}.-]{3,60})"', t)))[:15],
                }
                if k == "xy_home":
                    item["links"] = sorted(set(re.findall(r'href="(https?://[^"]+)"', t)))[:25]
                out[k] = item
            except Exception as e:  # noqa: BLE001
                out[k] = {"error": f"{type(e).__name__}: {e}"}
    (ROOT / "work" / "_chan3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
