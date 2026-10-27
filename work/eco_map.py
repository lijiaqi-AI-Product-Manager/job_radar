"""用 Playwright 解析 ATS 生态地图：从北森/大易/Moka 的「客户案例」页抓公司名，
扩充候选池（这些公司必然有招聘门户）。

合规边界：
  - 只读公开营销页（无登录、无验证码）
  - 每 host 串行 1 rps，不并发同一 host
  - 不猜接口、不逆加密，只提取页面上公开渲染的公司名
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

TARGETS = [
    ("beisen", "https://www.beisen.com/customer/"),
    ("beisen", "https://www.beisen.com/"),
    ("dayee", "https://www.dayee.com/"),
    ("dayee", "https://www.dayee.com/case/"),
    ("moka", "https://www.mokahr.com/customers"),
    ("moka", "https://www.mokahr.com/"),
    ("feishu", "https://www.feishu.cn/hc/zh-CN/articles/360049067486"),
]


def main() -> None:
    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="zh-CN")
        for sign, url in TARGETS:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                for _ in range(6):
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(400)
                text = page.inner_text("body")
                title = page.title()
            except Exception as e:  # noqa: BLE001
                print(f"ERR {url} {type(e).__name__}")
                page.close()
                continue
            finally:
                pass
            page.close()
            (WORK / f"eco_{sign}_{re.sub(r'[^a-z0-9]+', '_', url)[-40:]}.txt").write_text(
                text, encoding="utf-8")
            out.append({"sign": sign, "url": url, "title": title, "chars": len(text)})
            print(f"{sign:<7}{url:<45}{len(text):>7} chars  {title[:40]}", flush=True)
            time.sleep(1.0)
        browser.close()
    (WORK / "eco_pages.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                         encoding="utf-8")


if __name__ == "__main__":
    main()
