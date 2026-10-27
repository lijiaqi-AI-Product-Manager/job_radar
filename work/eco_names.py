"""用 Playwright 从 ATS 厂商客户页提取公司名（分批、按卡片结构取），产出扩充候选池。

做法：定位「案例卡片」里的公司名节点，而不是整页文本（整页文本会把行业标签混进来）。
每个 ATS 厂商站一个 host，串行 1 rps。
"""

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

PAGES = [
    ("beisen", "https://www.beisen.com/customer/", 8),
    ("dayee", "https://www.dayee.com/customer/", 6),
    ("dayee", "https://www.dayee.com/", 4),
    ("moka", "https://www.mokahr.com/customer", 6),
    ("moka", "https://www.mokahr.com/customers", 6),
]

# 卡片里公司名常见的选择器，按优先级尝试
SELS = ["h3", "h4", ".name", ".title", ".company", ".logo-name", "p", "span"]

COMPANY_HINT = re.compile(r"(公司|集团|银行|证券|基金|保险|汽车|科技|药业|医药|电器|电子|"
                          r"地产|置业|物流|航空|钢|化工|food|tech|group)", re.I)


def harvest(page) -> list[str]:
    names: list[str] = []
    for sel in SELS:
        for el in page.query_selector_all(sel):
            try:
                t = (el.inner_text() or "").strip().replace("\n", " ")
            except Exception:  # noqa: BLE001
                continue
            if not t or len(t) > 24:
                continue
            if t in names:
                continue
            names.append(t)
        if len(names) > 400:
            break
    return names


def main() -> None:
    found: dict[str, dict] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="zh-CN",
                                  viewport={"width": 1440, "height": 900})
        for sign, url, rounds in PAGES:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
                names: list[str] = []
                for _ in range(rounds):
                    page.mouse.wheel(0, 1600)
                    page.wait_for_timeout(900)
                    for n in harvest(page):
                        if n not in names:
                            names.append(n)
                title = page.title()
            except Exception as e:  # noqa: BLE001
                print(f"ERR {url} {type(e).__name__}", flush=True)
                page.close()
                continue
            page.close()
            print(f"{sign:<7}{url:<42}{len(names):>4} 个候选名  {title[:34]}", flush=True)
            for n in names:
                found.setdefault(n, {"name": n, "seen_on": []})
                if url not in found[n]["seen_on"]:
                    found[n]["seen_on"].append(url)
                found[n]["vendor"] = sign
            time.sleep(1.0)
        browser.close()
    (WORK / "eco_names.json").write_text(
        json.dumps(list(found.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"合计 {len(found)} 个去重名称")


if __name__ == "__main__":
    main()
