"""探测 智联校招 / 51job / 牛客 是否有「按公司名查岗位」的公开入口。

只做合规判断 + 结构识别，不写数据。结果写 work/_chan2.json（UTF-8）。
"""

import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

TARGETS = {
    "xy_home": "https://xiaoyuan.zhaopin.com/",
    "xy_jobs": "https://xiaoyuan.zhaopin.com/jobs/",
    "xy_robots": "https://xiaoyuan.zhaopin.com/robots.txt",
    "we_robots": "https://we.51job.com/robots.txt",
    "xyz": "https://xyz.51job.com/",
    "campus51": "https://campus.51job.com/",
    "nc_company": "https://www.nowcoder.com/jobs/recommend/campus",
}


def scan(html: str) -> dict:
    out = {}
    out["initial_state"] = html.find("__INITIAL_STATE__")
    out["nuxt"] = html.find("__NUXT__")
    out["api_hosts"] = sorted(set(re.findall(r"https?://([a-z0-9.-]*api[a-z0-9.-]*)", html)))[:12]
    out["company_paths"] = sorted(set(re.findall(r'"(/(?:company|jobs?|firm|ent)[a-zA-Z0-9/_-]{2,40})"', html)))[:15]
    out["n_a"] = html.count("<a ")
    out["len"] = len(html)
    return out


def main() -> None:
    res: dict[str, dict] = {}
    with httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": UA}) as c:
        for name, url in TARGETS.items():
            try:
                r = c.get(url)
                text = r.text
                item = {"status": r.status_code, "final": str(r.url), **scan(text)}
                item["head"] = re.sub(r"\s+", " ", text[:200])
                if name.endswith("robots"):
                    item["robots"] = text[:800]
                res[name] = item
            except Exception as e:  # noqa: BLE001
                res[name] = {"error": f"{type(e).__name__}: {e}"}
    (ROOT / "work" / "_chan2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
