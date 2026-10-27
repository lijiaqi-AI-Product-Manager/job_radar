"""从已确认站点抓页脚/友链里的 *.edu.cn，扩充候选集。"""
import json
import re

from playwright.sync_api import sync_playwright

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")
SEEDS = ["job.xidian.edu.cn", "career.gdut.edu.cn", "job.zzu.edu.cn", "job.neuq.edu.cn",
         "career.shiep.edu.cn", "xsjyzd.jmu.edu.cn", "career.hznu.edu.cn"]
found = {}
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = b.new_context(user_agent=UA, ignore_https_errors=True)
    pg = ctx.new_page()
    for s in SEEDS:
        try:
            pg.goto(f"https://{s}/campus", wait_until="domcontentloaded", timeout=25000)
            pg.wait_for_timeout(3500)
            links = pg.eval_on_selector_all("a", "els=>els.map(e=>[e.href,e.innerText.trim().slice(0,20)])")
        except Exception as e:
            print(s, "err", e)
            continue
        for href, txt in links:
            if "edu.cn" in href:
                m = re.match(r"https?://([^/]+)", href)
                if m and m.group(1) != s:
                    found.setdefault(m.group(1), set()).add(txt)
        print(s, len(found))
    b.close()
out = {k: "/".join(sorted(v))[:40] for k, v in found.items()}
json.dump(out, open("/workspace/job_radar/work/edu_footer_hosts.json", "w"), ensure_ascii=False, indent=1)
for k in sorted(out):
    print(k, "|", out[k])
