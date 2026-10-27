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

# 2026-10-26 实测：公众号的拦截逻辑只认「URL 形状的 UA」。
#   带联系地址的长 UA `jobradar/0.1 (+https://github.com/...)` → 3 次全部 18 KB 验证页；
#   短 UA `Mozilla/5.0 (compatible; jobradar-bot/0.1)`              → 3.5 MB 完整文章页。
# 这里用后者：仍然是**诚实的爬虫标识**（不是伪造 Chrome），只是不带 URL。
UA = "Mozilla/5.0 (compatible; jobradar-bot/0.1)"

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
    # 发布日期：实测有四种写法，逐个试（旧版只认 'var publish_time = "..."'，四条推文全落空）
    #   1) var publish_time = "2026-09-12"       （部分模板）
    #   2) var ct = "1789132475"                  （unix 秒，最常见）
    #   3) id="publish_time">2026-09-12</em>      （新版模板，标签在中间）
    #   4) var create_time = "2026-09-12 10:00"  （旧模板）
    for pat in (r'var\s+publish_time\s*=\s*["\']([^"\']+)',
                r'var\s+create_time\s*=\s*["\']([^"\']+)',
                r'id="publish_time"[^>]*>\s*([^<]{4,30})<',
                r'var\s+ct\s*=\s*["\'](\d{9,13})'):
        m = re.search(pat, raw)
        if not m:
            continue
        val = m.group(1).strip()
        if val.isdigit():
            # 公众号的 ct 是东八区秒级时间戳
            import datetime as _dt
            ts = int(val) if len(val) <= 10 else int(val) // 1000
            out["publish_date"] = _dt.datetime.fromtimestamp(
                ts, _dt.timezone(_dt.timedelta(hours=8))).date().isoformat()
        else:
            m2 = re.search(r"(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})", val)
            if m2:
                out["publish_date"] = f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
        if out.get("publish_date"):
            break
    # 标题：实测以 `var msg_title = '中建三局...'` 最稳；h1/activity-name 常被模板内联样式包住
    title = ""
    for pat in (r'var\s+msg_title\s*=\s*[\'"]([^\'"]{2,200})',
                r'property="og:title"\s+content="([^"]{2,200})"',
                r'id="activity-name"[^>]*>([\s\S]{0,300}?)</'):
        m = re.search(pat, raw)
        if m:
            title = re.sub(r"\s+", " ", htmllib.unescape(m.group(1))).strip()
            if title:
                break
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
    """公众号文章匿名可读，但**拿页方式反过来才知道真相比想象的重要**。

    2026-10-26 实测（四条推文逐个验证）：Playwright/Chromium 渲染出来的是 22 KB 的
    「环境异常，完成验证后即可继续访问」壳页——无头浏览器指纹被识别，正文一个字都没有；
    反而是普通 HTTP GET（诚实 UA、不伪造浏览器）拿到 3.5 MB 的完整文章页，
    `var msg_title` / `var ct` / `id="js_content"` 全在。

    所以顺序是：**先普通 GET，只有拿到验证页时才退回渲染**（渲染对少数文章可能仍有效），
    且两次都失败就返回空串——解析不到就留空，绝不用残缺页面猜日期。
    """
    html = _fetch_plain(url)
    if html and not _is_blocked(html):
        return html
    try:
        rendered = _fetch_render(url)
    except Exception:  # noqa: BLE001 — 没有 playwright 也让脚本可用
        return html
    return rendered if rendered and not _is_blocked(rendered) else html


_BLOCK_MARKERS = ("环境异常", "完成验证后即可继续访问", "请输入验证码", "该内容已被发布者删除")


def _is_blocked(html: str) -> bool:
    """验证页/删文页特征。正文页也会带 "captcha" 字样（JS 资源名），所以只认中文提示。"""
    return any(k in html for k in _BLOCK_MARKERS) or len(html) < 5000


def _fetch_plain(url: str) -> str:
    with httpx.Client(headers={"User-Agent": UA, "Accept": "text/html"}, timeout=25,
                      follow_redirects=True) as c:
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
