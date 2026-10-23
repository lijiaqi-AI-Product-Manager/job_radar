"""解析官方公众号推文，抽取「网申时间 / 届次 / 项目类型 / 城市」——日历里最缺的就是这些。

公众号推文（mp.weixin.qq.com）是公开页面，匿名可读；标题里几乎必写届次，
正文里通常写「网申时间：2026年9月1日—10月31日」。这是「网申时间」字段最可靠的来源。

用法：
    uv run python scripts/wechat_parse.py --url https://mp.weixin.qq.com/s/xxxx
    uv run python scripts/wechat_parse.py --file urls.json --out wechat-parsed.json

红线：只读公开推文，不登录；解析不到就留空。
"""

import argparse
import html as htmllib
import json
import re
import sys
from pathlib import Path

import httpx

UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, polite crawler; contact via GitHub issues)"

YEAR = re.compile(r"(20\d{2})\s*届|(\d{2})\s*届")
PROJECT = ("秋招正式批", "秋招提前批", "提前批", "秋招", "春招", "暑期实习", "寒假实习", "日常实习",
           "校园大使", "实习生", "校招", "社招", "兼职", "线上")
CN_DATE = r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?"
RANGE = re.compile(
    CN_DATE + r"\s*(?:—|－|~|～|至|到|-|—{1,2})\s*(?:(20\d{2})[年./-])?(\d{1,2})[月./-](\d{1,2})日?")
WINDOW_KW = re.compile(r"(网申|报名|投递|申请|简历|截止|招聘时间|时间安排)")
CITIES = (
    "北京 上海 广州 深圳 杭州 成都 南京 武汉 西安 苏州 天津 重庆 长沙 郑州 合肥 济南 青岛 厦门 福州 "
    "宁波 无锡 东莞 佛山 昆明 贵阳 南宁 南昌 太原 石家庄 沈阳 大连 长春 哈尔滨 兰州 海口 三亚 香港"
).split()


def _text(raw: str) -> str:
    txt = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"[ \t\u3000]+", " ", htmllib.unescape(txt))


def parse(raw: str) -> dict:
    out: dict = {}
    m = re.search(r'var\s+publish_time\s*=\s*["\']([\d-]+)', raw) or re.search(
        r'id="publish_time"[^>]*>([^<]+)<', raw)
    if m:
        out["publish_date"] = m.group(1).strip()[:10]
    t = re.search(r'id="activity-name"[^>]*>(.*?)<', raw, re.S)
    title = re.sub(r"\s+", " ", htmllib.unescape(t.group(1))).strip() if t else ""
    body = _text(raw)
    text = (title + "\n" + body)[:200_000]
    m = YEAR.search(text)
    if m:
        y = m.group(1) or ("20" + m.group(2))
        if 2024 <= int(y) <= 2032:
            out["grad_year"] = int(y)
    proj = [p for p in PROJECT if p in text]
    if proj:
        out["project_types"] = proj[:4]
    best = None
    for mm in RANGE.finditer(text):
        g = mm.groups()
        start = f"{g[0]}-{int(g[1]):02d}-{int(g[2]):02d}"
        end = f"{g[3] or g[0]}-{int(g[4]):02d}-{int(g[5]):02d}"
        if not (start < end):
            continue
        if not start.startswith(("2025", "2026", "2027")):
            continue
        ctx = text[max(0, mm.start() - 40):mm.start() + 40]
        score = 2 if WINDOW_KW.search(ctx) else 1
        if best is None or score > best[0]:
            best = (score, start, end)
    if best:
        out["apply_start"], out["apply_end"] = best[1], best[2]
    cities = [c for c in CITIES if c in text]
    if cities:
        out["cities"] = cities[:12]
    out["title"] = title[:80]
    return out


def fetch(url: str) -> str:
    """公众号文章对非浏览器 UA 会返回空壳页，所以优先用渲染（Playwright，已批准）。"""
    try:
        return _fetch_render(url)
    except Exception:
        pass
    with httpx.Client(headers={"User-Agent": UA}, timeout=25, follow_redirects=True) as c:
        r = c.get(url)
        return r.text if r.status_code == 200 else ""


def _fetch_render(url: str) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(locale="zh-CN")
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            html = page.content()
        finally:
            page.close()
            b.close()
    return html


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--file")
    ap.add_argument("--out", default="wechat-parsed.json")
    args = ap.parse_args()
    urls = []
    if args.url:
        urls = [args.url]
    elif args.file:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        urls = data if isinstance(data, list) else list(data)
    else:
        print("need --url or --file", file=sys.stderr)
        return 2
    out = {}
    for u in urls:
        try:
            got = parse(fetch(u))
        except Exception as e:  # noqa: BLE001
            print(f"ERR {u[:60]} {type(e).__name__}", file=sys.stderr)
            continue
        got["url"] = u
        out[u] = got
        print(f"{got.get('publish_date')} | {got.get('grad_year')}届 | "
              f"{got.get('apply_start')}~{got.get('apply_end')} | {got.get('title')[:40]}", flush=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
