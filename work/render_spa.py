"""渲染通道：对「纯 JS 渲染、无公开 JSON」的招聘站，用 Playwright 拿真实正文。

依据 CLAUDE.md 铁律 6（2026-10-21 用户批准）：
> 浏览器渲染（Playwright）可用，但只在公开页面必须执行 JS 才能拿到内容、
> 且找不到公开 JSON 接口时使用。固定 UA、限速、robots 规则同样适用；
> 渲染中出现验证码/登录框立即停止并标 blocked。
> 优先级仍是：公开 JSON 接口 > 服务端渲染 HTML > 浏览器渲染。

所以本脚本只处理 work/fields.jsonl 里 `max(page.len) < 800` 的「SPA 壳」公司，
且跳过已有结构化 ATS 接口的（beisen/hotjob 已由 extract_fields 覆盖）。

红线落实：
- 固定项目 UA（context.user_agent），不伪装浏览器；
- 同主机串行，每次导航间隔 ≥1s；
- 出现验证码 / 登录框 → 立即 close，记 blocked，不尝试绕过；
- 每个站点最多等 8s 网络空闲 + 2 次滚动（触发懒加载），不点击任何交互；
- 只落盘纯文本（不含 cookie/token）。

用法：
    python3 work/render_spa.py --limit 20       # 试点
    python3 work/render_spa.py                  # 全量
输出：work/rendered.jsonl（company / url / text / blocked / note）
"""

import argparse
import json
import queue
import re
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar_extract import strip_tags  # noqa: E402

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

BLOCK_MARK = re.compile(r"验证码|滑块验证|安全验证|人机验证|请输入验证码|请先登录|登录后查看|"
                        r"访问受限|账号登录|扫码登录|Just a moment|Enable JavaScript", re.I)

# 招聘站里「职位列表/公告」常见的导航文案
NAV = re.compile(r"校园招聘|社会招聘|职位列表|招聘职位|全部职位|岗位列表|招聘公告|公告|"
                 r"实习招聘|校招|加入我们|热招职位|campus", re.I)


def page_text(page) -> str:
    html = page.content()
    return strip_tags(html)


def render_one(browser, item: dict) -> dict:
    """渲染一家公司，带**硬超时**。

    实测有站点会让 Playwright 的 goto/networkidle 永久挂起（页面持续发请求、
    或有 3rd-party 脚本不收敛），单靠 page timeout 兜不住。这里用独立线程 + join(45s)，
    超时就放弃这家，继续下一家——绝不能因为一个坏站点卡死整批。

    重要：Playwright 的 sync API 是**线程绑定**的（greenlet），browser 在主线程创建、
    在子线程里用会抛 greenlet.error: cannot switch to a different thread。
    所以子线程必须自己起一套 sync_playwright，结果用 Queue 送回来。
    """
    q: queue.Queue[dict] = queue.Queue(maxsize=1)

    def _run() -> None:
        try:
            with sync_playwright() as p:
                br = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
                try:
                    q.put(_render_inner(br, item))
                finally:
                    try:
                        br.close()
                    except Exception:
                        pass
        except Exception as e:
            q.put({"company": item["company"], "url": item["url"], "text": "",
                   "blocked": False, "note": f"err:{type(e).__name__}",
                   "pages": [], "titles": []})

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    try:
        return q.get(timeout=45.0)
    except queue.Empty:
        return {"company": item["company"], "url": item["url"], "text": "", "blocked": False,
                "note": "timeout", "pages": [], "titles": []}


def _render_inner(browser, item: dict) -> dict:
    company, url = item["company"], item["url"]
    out = {"company": company, "url": url, "text": "", "blocked": False,
           "note": "", "pages": [], "titles": []}
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 1000},
                              locale="zh-CN", java_script_enabled=True)
    pg = ctx.new_page()
    pg.set_default_timeout(15000)
    try:
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            out["note"] = f"goto:{type(e).__name__}"
            return out
        try:
            pg.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        # 触发懒加载：慢滚到底再回顶，最多 2 轮
        for _ in range(2):
            pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            pg.wait_for_timeout(900)
        pg.evaluate("window.scrollTo(0, 0)")
        pg.wait_for_timeout(400)

        text = page_text(pg)
        out["pages"].append({"url": pg.url, "len": len(text)})

        if BLOCK_MARK.search(text[:3000]) or BLOCK_MARK.search(pg.title() or ""):
            out["blocked"] = True
            out["note"] = "captcha_or_login"
            return out

        # 如果首页只有壳，找站内「校园招聘 / 职位列表」入口点进去（仅点击导航链接，不做其它交互）
        if len(text) < 600:
            hrefs = pg.eval_on_selector_all(
                "a", "els => els.map(e => ({t:(e.innerText||'').trim(), h:e.href}))")
            cand = [(h["h"], h["t"]) for h in hrefs
                    if h.get("h") and h["h"].startswith("http") and NAV.search(h.get("t") or "")]
            seen = set()
            for h, t in cand:
                if len(out["pages"]) >= 3:
                    break
                if h in seen:
                    continue
                seen.add(h)
                try:
                    pg.goto(h, wait_until="domcontentloaded", timeout=20000)
                    try:
                        pg.wait_for_load_state("networkidle", timeout=7000)
                    except Exception:
                        pass
                    pg.wait_for_timeout(700)
                    t2 = page_text(pg)
                    out["pages"].append({"url": pg.url, "len": len(t2), "label": t[:20]})
                    if BLOCK_MARK.search(t2[:3000]):
                        out["blocked"] = True
                        out["note"] = "captcha_or_login_sub"
                        break
                    text += "\n" + t2
                except Exception:
                    continue

        out["text"] = text[:80000]
        if not out["note"]:
            out["note"] = "ok" if len(text) > 600 else "still_empty"
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--src", default="work/fields.jsonl")
    ap.add_argument("--out", default="work/rendered.jsonl")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    fields = []
    for s in (ROOT / args.src).read_text(encoding="utf-8").splitlines():
        if not s.strip():
            continue
        try:
            fields.append(json.loads(s))
        except json.JSONDecodeError:
            continue  # 上次被强杀写出的半行，跳过即可
    shell = [r for r in fields
             if r.get("kind") == "site" and r.get("pages")
             and max((p.get("len") or 0) for p in r["pages"]) < 800]

    outfile = ROOT / args.out
    done = set()
    if outfile.exists():
        # 上次若被强杀，末尾会留半行 JSON。这里逐行容错读取，并顺手把坏行剔掉重写，
        # 免得每次续跑都在同一行崩。
        good, bad = [], 0
        for s in outfile.read_text(encoding="utf-8").splitlines():
            if not s.strip():
                continue
            try:
                good.append(json.loads(s))
            except json.JSONDecodeError:
                bad += 1
        if bad:
            outfile.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in good),
                              encoding="utf-8")
            print(f"清理损坏行 {bad}", file=sys.stderr)
        done = {r["company"] for r in good if "company" in r}
    todo = [r for r in shell if r["company"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"shell={len(shell)} done={len(done)} todo={len(todo)}", file=sys.stderr)

    n, t0 = 0, time.time()
    if True:  # 单页浏览器实例由 render_one 内的子线程自行起停（见函数 docstring）
      with open(outfile, "a", encoding="utf-8") as fh:
        # 同主机串行：按 host 分组，组内间隔 1.2s
        todo.sort(key=lambda r: r["host"])
        last_host, last_at = None, 0.0
        for item in todo:
            h = item["host"]
            if h == last_host:
                gap = time.monotonic() - last_at
                if gap < 1.2:
                    time.sleep(1.2 - gap)
            last_host, last_at = h, time.monotonic()
            try:
                rec = render_one(None, item)
            except Exception as e:
                rec = {"company": item["company"], "url": item["url"], "text": "",
                       "blocked": False, "note": f"err:{type(e).__name__}", "pages": [], "titles": []}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 10 == 0:
                rate = n / max(time.time() - t0, 1) * 60
                print(f"[{n}/{len(todo)}] {rate:.1f} 家/分", file=sys.stderr)
            if time.time() - t0 > args.timeout * 60:
                print("time budget reached", file=sys.stderr)
                break
        pass
    print(f"done {n} in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
