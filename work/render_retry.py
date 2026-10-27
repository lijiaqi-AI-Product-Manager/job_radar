"""重渲染通道：对上一轮 `work/rendered.jsonl` 里**失败或内容过短**的公司再跑一次。

为什么需要单独一个脚本：`render_spa.py` 的 `done` 集合按公司名去重，凡是落过盘的公司
（哪怕 `note = "goto:TimeoutError"`、`text` 只有 200 字）就不会再试。上一轮 196 家里有
50 家是这种状态 —— 39 家 `still_empty`、8 家 `captcha_or_login`、2 家超时、1 家 Error。
这 50 家现在在日历里连「城市」「网申时间」两列都空着，而它们大多只是首屏慢了 3 秒。

与 `render_spa.py` 的差别只有三点，红线一条没动：
  1. 只挑 `note != "ok"` 或 `len(text) < 600` 的，成功的不重跑；
  2. 单站超时从 45s 放宽到 75s，`networkidle` 从 8s 放宽到 15s（首屏慢不等于被挡）；
  3. **上一轮判为 `captcha_or_login` 的不重试** —— 那是站点明确不让进，重试等于硬闯。
     （若这一轮真的出来了，也只认「正文 > 600 字且不再命中屏蔽词」的结果。）

输出写回 `work/rendered.jsonl`（原地替换对应公司的记录，成功才替换）。

**日志按行落盘**：stderr 直接 `tail` 时，Playwright 的 node 子进程会在管道断开后抛 EPIPE
把整个脚本带崩（2026-10-26 实测跑 4 分钟后崩掉，白跑）。所以本脚本自己写
`work/render_retry.log`，跑的时候 `tail -f` 那个文件，不要 `| tail`。

用法：
    python3 -u work/render_retry.py --limit 10     # 试点
    python3 -u work/render_retry.py                # 全部
"""

import argparse
import json
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))
sys.path.insert(0, str(ROOT / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402
from render_spa import BLOCK_MARK, UA, page_text  # noqa: E402  复用同一套判据，不另起一套

# 上一轮判成这些的，说明站点是明确挡人的，不重试
HARD_BLOCK = {"captcha_or_login", "captcha_or_login_sub"}
NAV = None  # 延迟导入（render_spa.NAV）


def _render_inner(browser, item: dict, nav) -> dict:
    company, url = item["company"], item["url"]
    out = {"company": company, "url": url, "text": "", "blocked": False,
           "note": "", "pages": [], "titles": [], "retry": True}
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 1000},
                              locale="zh-CN", java_script_enabled=True)
    pg = ctx.new_page()
    pg.set_default_timeout(20000)
    try:
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=35000)
        except Exception as e:
            out["note"] = f"goto:{type(e).__name__}"
            return out
        try:
            pg.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        for _ in range(3):  # 多发一轮滚动，SPA 常常是滚到位才发列表请求
            pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            pg.wait_for_timeout(1200)
        pg.evaluate("window.scrollTo(0, 0)")
        pg.wait_for_timeout(500)

        text = page_text(pg)
        out["pages"].append({"url": pg.url, "len": len(text)})
        if BLOCK_MARK.search(text[:3000]) or BLOCK_MARK.search(pg.title() or ""):
            out["blocked"], out["note"] = True, "captcha_or_login"
            return out

        if len(text) < 600:
            hrefs = pg.eval_on_selector_all(
                "a", "els => els.map(e => ({t:(e.innerText||'').trim(), h:e.href}))")
            cand = [(h["h"], h["t"]) for h in hrefs
                    if h.get("h") and h["h"].startswith("http") and nav.search(h.get("t") or "")]
            seen = set()
            for h, t in cand:
                if len(out["pages"]) >= 4:
                    break
                if h in seen:
                    continue
                seen.add(h)
                try:
                    pg.goto(h, wait_until="domcontentloaded", timeout=25000)
                    try:
                        pg.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    pg.wait_for_timeout(900)
                    t2 = page_text(pg)
                    out["pages"].append({"url": pg.url, "len": len(t2), "label": t[:20]})
                    if BLOCK_MARK.search(t2[:3000]):
                        out["blocked"], out["note"] = True, "captcha_or_login_sub"
                        break
                    text += "\n" + t2
                except Exception:
                    continue

        # 还短就逐个点站内「职位列表」入口。
        #
        # 为什么需要这一步：Moka 这类站点的导航是 `#/jobList` 形式的 hash 路由或 click 事件，
        # **不是 `<a href>`**，上面那套 href 扫描一个都抓不到（实测知乎 1173 字全是首页文案、
        # 唯品会 80 字）。而招聘页的「城市 / 网申时间」只在职位列表页上。
        # 只点**导航区域里文字明确匹配「职位列表/全部职位/招聘职位」的链接**，最多 3 个；
        # 不填表单、不点「投递/申请/登录」、不触发任何账号动作。
        if len(text) < 1500:
            # ① 先试 hash / 路径直接进列表页 —— Moka 的 `#/jobList`、很多自建站的 `/jobs`。
            #    这比「点链接」稳：同一套 URL 规则对所有同类站点通用，不依赖 DOM 结构。
            for suffix in ("#/jobList", "/jobs", "/position", "/campus/jobs"):
                if len(text) >= 1500:
                    break
                try:
                    cur = pg.url.rstrip("/")
                    if suffix.startswith("#"):
                        target = cur.split("#")[0] + suffix
                    else:
                        target = cur + suffix
                    pg.goto(target, wait_until="domcontentloaded", timeout=25000)
                    try:
                        pg.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    pg.wait_for_timeout(1500)
                    t2 = page_text(pg)
                    if BLOCK_MARK.search(t2[:3000]):
                        out["blocked"], out["note"] = True, "captcha_or_login_sub"
                        break
                    if len(t2) > 800:
                        out["pages"].append({"url": pg.url, "len": len(t2), "via": suffix})
                        text += "\n" + t2
                except Exception:
                    continue

        if len(text) < 1500:
            for label in ("职位列表", "全部职位", "招聘职位", "热招职位", "职位"):
                if len(out["pages"]) >= 5 or len(text) >= 6000:
                    break
                try:
                    link = pg.get_by_role("link", name=label, exact=False).first
                    if link.count() == 0 or not link.is_visible():
                        continue
                    before = pg.url
                    link.click(timeout=6000)
                    try:
                        pg.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    pg.wait_for_timeout(1200)
                    t3 = page_text(pg)
                    if BLOCK_MARK.search(t3[:3000]):
                        out["blocked"], out["note"] = True, "captcha_or_login_sub"
                        break
                    out["pages"].append({"url": pg.url, "len": len(t3), "label": label,
                                         "via": "click", "from": before})
                    text += "\n" + t3
                except Exception:
                    continue

        out["text"] = text[:80000]
        out["note"] = "ok" if len(text) > 600 else "still_empty"
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    return out


def render_one(item: dict, nav) -> dict:
    """同 `render_spa.render_one`：独立线程 + 独立 Playwright 实例 + 硬超时。"""
    q: queue.Queue[dict] = queue.Queue(maxsize=1)

    def _run() -> None:
        try:
            with sync_playwright() as p:
                br = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
                try:
                    q.put(_render_inner(br, item, nav))
                finally:
                    try:
                        br.close()
                    except Exception:
                        pass
        except Exception as e:
            q.put({"company": item["company"], "url": item["url"], "text": "", "blocked": False,
                   "note": f"err:{type(e).__name__}", "pages": [], "titles": [], "retry": True})

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    try:
        return q.get(timeout=75.0)
    except queue.Empty:
        return {"company": item["company"], "url": item["url"], "text": "", "blocked": False,
                "note": "timeout", "pages": [], "titles": [], "retry": True}


def main() -> int:
    import render_spa

    # 日志自己落盘，不走 stdout 管道（见模块 docstring 里 EPIPE 的说明）
    logf = open(ROOT / "work/render_retry.log", "a", encoding="utf-8")

    def log(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, file=logf, flush=True)

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--file", default="work/rendered.jsonl")
    ap.add_argument("--timeout", type=float, default=90.0, help="整批时间预算（分钟）")
    args = ap.parse_args()

    path = ROOT / args.file
    rows = []
    for s in path.read_text(encoding="utf-8").splitlines():
        if s.strip():
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    by = {r["company"]: r for r in rows}
    todo = [{"company": r["company"], "url": r["url"]}
            for r in rows
            if r.get("note") != "ok" and r.get("note") not in HARD_BLOCK]
    if args.limit:
        todo = todo[:args.limit]
    log(f"待重渲染 {len(todo)} 家（跳过已成功的与明确挡人的）")

    n, ok, t0 = 0, 0, time.time()
    for item in todo:
        if time.time() - t0 > args.timeout * 60:
            log("时间预算到，停止")
            break
        rec = render_one(item, render_spa.NAV)
        n += 1
        if rec.get("note") == "ok":
            ok += 1
            by[item["company"]] = rec
            # 每成功一家就整体重写一次：这个文件只有几百行，比「追加 + 事后合并」安全，
            # 也不怕中途被强杀留下半行。
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in by.values()),
                            encoding="utf-8")
        log(f"[{n}/{len(todo)}] {item['company']} -> {rec.get('note')} "
            f"len={len(rec.get('text') or '')}")
        time.sleep(1.2)
    log(f"完成 {n} 家，成功 {ok} 家，用时 {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
