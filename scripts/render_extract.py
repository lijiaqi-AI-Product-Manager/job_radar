"""渲染招聘页并抽取「日历需要的字段」——用于公开 JD 被挡、但页面本身能看到岗位列表的公司。

背景（2026-10-23 用户要求）：日历条目必须有 方向/岗位、城市、届次 等字段；
很多大厂的 API 有滑块/签名，但**网页上岗位列表是公开可见的**，所以用 Playwright 渲染后抽取。

红线：只读公开页面，不登录、不破解验证码；抽不到就留空。

用法：
    python scripts/render_extract.py --file calendar/enrich-targets.json --out enrich-open.json

输出 JSON：{id: {group, url, title, grad_year, project_type, cities:[], tracks:[{direction, roles}]}}
"""

import argparse
import json
import re
import sys
from pathlib import Path

YEAR = re.compile(r"(20\d{2})\s*届")
PROJECT = re.compile(r"(秋招|春招|提前批|暑期实习|寒假实习|日常实习|校园大使|实习生|校招|社招)")
CITIES = (
    "北京 上海 广州 深圳 杭州 成都 南京 武汉 西安 苏州 天津 重庆 长沙 郑州 合肥 济南 青岛 厦门 福州 "
    "宁波 无锡 东莞 佛山 珠海 中山 惠州 昆明 贵阳 南宁 南昌 太原 石家庄 沈阳 大连 长春 哈尔滨 兰州 "
    "乌鲁木齐 呼和浩特 银川 西宁 拉萨 海口 三亚 温州 绍兴 嘉兴 金华 台州 常州 南通 徐州 扬州 盐城 "
    "洛阳 烟台 潍坊 临沂 唐山 保定 廊坊 赣州 宜昌 襄阳 株洲 湘潭 衡阳 绵阳 德阳 宜宾 遵义 柳州 桂林 "
    "香港 澳门 台北"
).split()
JOB_HINT = re.compile(r"(工程师|开发|算法|产品|设计|运营|销售|管培|培训生|实习|分析师|研究员|顾问|经理|专员|架构师|测试|财务|人力|法务|市场)")


def extract(page) -> dict:
    """从已渲染页面抽取字段。tracks 用「页面上的岗位标题」聚合。"""
    text = page.inner_text("body")[:200_000]
    out: dict = {}
    m = YEAR.search(text)
    if m and 2024 <= int(m.group(1)) <= 2032:
        out["grad_year"] = int(m.group(1))
    proj = sorted({m.group(1) for m in PROJECT.finditer(text)})
    if proj:
        out["project_types"] = proj[:4]
    cities = [c for c in CITIES if c in text]
    if cities:
        out["cities"] = cities[:12]
    # 岗位标题：优先取链接文字/列表项里带岗位关键词的短文本
    titles: list[str] = []
    for sel in ("a", "li", "div"):
        try:
            nodes = page.query_selector_all(sel)
        except Exception:
            continue
        for n in nodes[:4000]:
            try:
                t = (n.inner_text() or "").strip()
            except Exception:
                continue
            if 4 <= len(t) <= 30 and JOB_HINT.search(t) and "<" not in t:
                titles.append(t)
        if len(titles) >= 300:
            break
    seen = []
    for t in titles:
        if t not in seen:
            seen.append(t)
    if seen:
        out["job_titles"] = seen[:120]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--out", default="enrich-open.json")
    args = ap.parse_args()
    targets = json.loads(Path(args.file).read_text(encoding="utf-8"))
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (compatible; jobradar/0.1; +https://github.com/lijiaqimun-coder/job_radar) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            viewport={"width": 1366, "height": 900},
        )
        for item in targets:
            url = item["url"]
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3500)
                data = extract(page)
                data.update({"group": item.get("group"), "url": url, "title": page.title()[:60]})
                results[item["id"]] = data
                print(f"OK {item.get('group')} titles={len(data.get('job_titles') or [])} "
                      f"cities={len(data.get('cities') or [])}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"ERR {item.get('group')} {type(e).__name__}: {e}"[:160], flush=True)
            finally:
                page.close()
        browser.close()
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {args.out} ({len(results)} pages)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
