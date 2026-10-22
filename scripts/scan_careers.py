"""批量扫描公司官网，找官方招聘入口（爬虫友好、只看公开页面）。

用法：
    uv run python scripts/scan_careers.py domains.json [out.json]
    domains.json: {"公司名": "example.com", ...}

做法：抓首页（https://www. 优先，再试裸域）→ 找 href 里带
招聘/人才/加入我们/careers/join/jobs/zhaopin/campus/recruit 的链接 → 逐个验证标题。
输出每家公司 {group, home, careers:{url,title}|None}，供人工核对后写入日历。
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, polite crawler; contact via GitHub issues)"
KEYS = re.compile(r"招聘|人才|加入我们|careers?|join|jobs?|zhaopin|campus|recruit", re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def _title(html: str) -> str:
    m = TITLE.search(html)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:60] if m else ""


def probe(item: tuple[str, str]) -> dict:
    name, domain = item
    out = {"group": name, "home": None, "careers": None, "title": ""}
    with httpx.Client(headers={"User-Agent": UA}, timeout=8, follow_redirects=True) as c:
        for prefix in (f"https://www.{domain}", f"https://{domain}", f"http://www.{domain}"):
            try:
                r = c.get(prefix)
            except Exception:
                continue
            if r.status_code != 200 or len(r.text) < 800:
                continue
            out["home"], out["title"] = str(r.url), _title(r.text)
            links = []
            for href in re.findall(r'href="([^"]{2,200})"', r.text):
                if KEYS.search(href):
                    try:
                        links.append(str(httpx.URL(str(r.url)).join(href)))
                    except Exception:
                        pass
            for url in links[:5]:
                try:
                    v = c.get(url)
                    t = _title(v.text)
                except Exception:
                    continue
                if v.status_code == 200 and ("招聘" in t or "career" in url.lower() or "job" in url.lower()):
                    out["careers"] = {"url": str(v.url), "title": t}
                    break
            break
    return out


def main() -> int:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".out.json")
    domains = json.loads(src.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(probe, domains.items()))
    dst.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    home = sum(1 for r in rows if r["home"])
    found = [r for r in rows if r["careers"]]
    print(f"首页可达 {home}/{len(rows)}，找到招聘页 {len(found)}")
    for r in found:
        print(f"{r['group']}\t{r['careers']['url']}\t{r['careers']['title'][:36]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
