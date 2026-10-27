"""单站点 Playwright 渲染探测：列表条目数 + 1 条详情页是否含过期时间/正文长度。"""
import json
import re
import sys
import time

from playwright.sync_api import sync_playwright

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")
ITEM = re.compile(r"/campus/view/id/(\d+)")
BLOCK = re.compile(r"验证码|安全验证|人机验证|captcha|请先登录|访问受限|Forbidden|403", re.I)


def probe(page, host, path="/campus", detail_wait=4000):
    rec = {"host": host, "path": path, "items": 0, "has_expire": False,
           "body_len": 0, "note": ""}
    url = f"https://{host}{path}"
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if resp:
            rec["_code"] = resp.status
        page.wait_for_timeout(3000)
        html = page.content()
        if "网址未找到" in html or "404 Not Found" in html:
            rec["note"] = "404"
            return rec
        if BLOCK.search(page.inner_text("body")[:2000]):
            rec["note"] = "blocked"
            return rec
        ids = list(dict.fromkeys(ITEM.findall(html)))
        rec["items"] = len(ids)
        if not ids:
            rec["note"] = "no items"
            return rec
        # 打开第一条详情
        page.goto(f"https://{host}/campus/view/id/{ids[0]}", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(detail_wait)
        dhtml = page.content()
        try:
            text = page.inner_text("body")
        except Exception:
            text = dhtml
        rec["has_expire"] = ("过期时间" in dhtml) or ("过期时间" in text)
        # 正文长度：取「过期时间」这一容器之后（正文与元数据同容器）的真实文本长度
        blen = page.evaluate("""()=>{
          const cands=[...document.querySelectorAll('div,article,section,td')];
          let best=0;
          for(const e of cands){
            const t=e.innerText||''; if(!t.includes('过期时间')) continue;
            if(t.length<200||t.length>60000) continue;
            if([...e.children].length>30) continue;
            best=Math.max(best,t.length);
          }
          return best;
        }""")
        m = re.search(r"(过期时间[：:][\s\S]{200,})", text)
        seg = m.group(1) if m else text
        rec["body_len"] = blen or len(seg)
        rec["excerpt"] = text[:300].replace("\n", " ")
    except Exception as e:
        rec["note"] = f"err:{type(e).__name__}"
    return rec


if __name__ == "__main__":
    targets = sys.argv[1:]
    res = []
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = br.new_context(user_agent=UA, ignore_https_errors=True)
        page = ctx.new_page()
        page.route(re.compile(r"\.(png|jpg|jpeg|gif|woff2?|ttf|mp4)$"), lambda r: r.abort())
        for t in targets:
            r = probe(page, t)
            res.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
            time.sleep(1.5)
        br.close()
    json.dump(res, open("/workspace/job_radar/work/edu_pw_last.json", "w"), ensure_ascii=False, indent=1)
