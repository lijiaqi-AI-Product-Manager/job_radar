"""从官方招聘页补全日历字段（届次 / 网申起止 / 城市 / 方向线索）。

需求（2026-10-23 用户明确）：日历条目必须带 集团/公司/届次/项目类型/方向/网申时间/城市/
投递入口/来源/时间戳；有公开 JD 就挂，被挡则只发日历并加提示语。

红线：只填页面**明写**的信息，抽不到就留空，不猜。
所以这里只认强模式：`2027届`、`2026-08-03 ~ 2026-12-31`、`网申时间：…`、页面正文里出现的城市全称。

用法：
    uv run python scripts/enrich_calendar.py --db ~/.jobradar/calendar.db            # 只报告
    uv run python scripts/enrich_calendar.py --db ~/.jobradar/calendar.db --apply    # 写回 yaml
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "calendar" / "entries"
# 与 wechat_parse.py / wechat_entries.py 同一个 UA：带 URL 的 UA 会被 mp.weixin.qq.com
# 判为抓取器、回 18 KB「环境异常」壳页（2026-10-26 实测四篇全拦），短 UA 正常。
UA = "Mozilla/5.0 (compatible; jobradar-bot/0.1)"

YEAR = re.compile(r"(20\d{2})\s*届")
RANGE = re.compile(
    r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})日?\s*(?:~|～|至|到|—|－|-)\s*"
    r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})日?")
CN_RANGE = re.compile(
    r"(?:网申|报名|申请)?(?:时间|日期)[：:]\s*(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})日?\s*"
    r"(?:~|～|至|到|—|－|-)\s*(?:(\d{4})[年./-])?(\d{1,2})[月./-](\d{1,2})日?")
CITY_HINT = re.compile(r"(?:工作地点|工作城市|城市)[：:]\s*([^\n<]{2,40})")


def fetch(url: str) -> str:
    with httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        if r.status_code != 200:
            return ""
        # 公众号/门户的验证页当正文解析会抽出"版权年份"之类假日期，宁可不填
        if any(k in r.text for k in ("环境异常", "完成验证后即可继续访问", "请输入验证码")):
            return ""
        return r.text


def _plausible(start: str, end: str) -> bool:
    """网申窗口的现实检查：2025~2028 年之间、跨度 3~400 天、start < end。

    页面里还有版权年份、文章日期、活动日期，一次宽松的正则会把它们当成网申时间。
    """
    if not (start < end):
        return False
    if not (start.startswith(("2025", "2026", "2027", "2028"))):
        return False
    from datetime import date
    def d(s):
        y, m, dd = (int(x) for x in s.split("-"))
        return date(y, m, dd)
    days = (d(end) - d(start)).days
    return 3 <= days <= 400


def parse_page(html: str) -> dict:
    out: dict = {}
    m = YEAR.search(html)
    if m:
        year = int(m.group(1))
        if 2024 <= year <= 2032:
            out["grad_year"] = year
    # 优先取「网申/报名/截止」附近的日期区间
    spans = []
    for mm in RANGE.finditer(html):
        g = mm.groups()
        start = f"{g[0]}-{int(g[1]):02d}-{int(g[2]):02d}"
        end = f"{g[3]}-{int(g[4]):02d}-{int(g[5]):02d}"
        spans.append((mm.start(), start, end))
    for mm in CN_RANGE.finditer(html):
        g = mm.groups()
        start = f"{g[0]}-{int(g[1]):02d}-{int(g[2]):02d}"
        end = f"{g[3] or g[0]}-{int(g[4]):02d}-{int(g[5]):02d}"
        spans.append((mm.start(), start, end))
    best = None
    for pos, start, end in spans:
        if not _plausible(start, end):
            continue
        ctx = html[max(0, pos - 60):pos + 60]
        score = 2 if re.search(r"网申|报名|投递|申请|截止|招聘时间", ctx) else 1
        if best is None or score > best[0]:
            best = (score, start, end)
    if best:
        out["apply_start"], out["apply_end"] = best[1], best[2]
    m = CITY_HINT.search(html)
    if m:
        out["cities_raw"] = m.group(1)[:40]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（调试用）")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, group_name, apply_url, grad_year, apply_start, apply_end, cities, origin "
        "FROM entry WHERE origin='manual' AND apply_url IS NOT NULL "
        "AND (grad_year IS NULL OR apply_start IS NULL OR cities IN ('','[]'))").fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f"待补全 {len(rows)} 条", file=sys.stderr)

    results = {}
    with httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True) as client:
        for i, r in enumerate(rows, 1):
            url = r["apply_url"]
            if not url or not url.startswith("http"):
                continue
            try:
                resp = client.get(url)
                html = resp.text if resp.status_code == 200 else ""
            except Exception:
                html = ""
            got = parse_page(html) if html else {}
            if got:
                results[r["id"]] = {"group": r["group_name"], "url": url, **got}
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}，已抽到 {len(results)} 条", file=sys.stderr)
            time.sleep(0.8)

    print(json.dumps(results, ensure_ascii=False, indent=1)[:4000])
    out_path = ROOT / "calendar" / "enrich-report.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n抽取结果写入 {out_path}（{len(results)} 条）", file=sys.stderr)
    if not args.apply:
        return 0

    applied = 0
    for p in ENTRIES.glob("*.yaml"):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        changed = False
        for e in doc.get("entries") or []:
            got = results.get(e.get("id"))
            if not got:
                continue
            for k in ("grad_year", "apply_start", "apply_end"):
                if got.get(k) and not e.get(k):
                    e[k] = got[k]
                    changed = True
        if changed:
            p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
            applied += 1
    print(f"写回 {applied} 个文件", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
