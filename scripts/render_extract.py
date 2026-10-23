"""渲染招聘页并抽取「日历需要的字段」。

背景（2026-10-23 用户纠正）：**日历级信息（有哪些岗位、什么方向、哪些城市）在官网是公开可见的**，
人和机器都能看到、不需要登录态；被挡的只是「JD 全文接口」。所以不能用「被挡」当借口——
这里用 Playwright 渲染 + 按站点配置的交互（点 tab / 滚动懒加载），把岗位列表读出来。

红线：只读公开页面，不登录、不破解验证码；抽不到就留空。

输入 `--file` 是 JSON 列表，每项：
    {"id": "...", "group": "字节跳动", "url": "https://jobs.bytedance.com/campus/position",
     "click": ["校园招聘"],      # 可选：依次点击这些文字（tab/筛选）
     "scroll": 8}                # 可选：滚动次数（触发懒加载）

输出 {id: {group,url,title,grad_year,project_types,cities,job_titles}}
"""

import argparse
import json
import re
import sys
from pathlib import Path

YEAR = re.compile(r"(20\d{2})\s*届")
PROJECT = re.compile(r"(秋招|春招|提前批|暑期实习|寒假实习|日常实习|校园大使|实习生|校招|社招|兼职)")
CITIES = (
    "北京 上海 广州 深圳 杭州 成都 南京 武汉 西安 苏州 天津 重庆 长沙 郑州 合肥 济南 青岛 厦门 福州 "
    "宁波 无锡 东莞 佛山 珠海 中山 惠州 昆明 贵阳 南宁 南昌 太原 石家庄 沈阳 大连 长春 哈尔滨 兰州 "
    "乌鲁木齐 呼和浩特 银川 西宁 拉萨 海口 三亚 温州 绍兴 嘉兴 金华 台州 常州 南通 徐州 扬州 盐城 "
    "洛阳 烟台 潍坊 临沂 唐山 保定 廊坊 赣州 宜昌 襄阳 株洲 湘潭 衡阳 绵阳 德阳 宜宾 遵义 柳州 桂林 "
    "香港 澳门 台北"
).split()
JOB_HINT = re.compile(
    r"(工程师|开发|算法|产品|设计|运营|销售|管培|培训生|实习|分析师|研究员|顾问|经理|专员|架构师|"
    r"测试|财务|人力|法务|市场|策划|美术|编辑|主播|店长|技师|专家)")
BAD = re.compile(
    r"(招聘|首页|更多|全部|搜索|登录|注册|上一页|下一页|查看|了解|投递|详情|隐私|协议|菜单|"
    r"客服|关于|联系|帮助|反馈|下载|关注|分享|登录/注册|岗位集合|职位集合)")
NOISE_SENTENCE = re.compile(r"(的|和|我们|覆盖|全球|服务|业务|公司|介绍|使命|愿景|文化|福利|流程)")


def extract(page) -> dict:
    text = page.inner_text("body")[:250_000]
    out: dict = {}
    m = YEAR.search(text)
    if m and 2024 <= int(m.group(1)) <= 2032:
        out["grad_year"] = int(m.group(1))
    proj = sorted({m.group(1) for m in PROJECT.finditer(text)})
    if proj:
        out["project_types"] = proj[:5]
    cities = [c for c in CITIES if c in text]
    if cities:
        out["cities"] = cities[:15]
    titles: list[str] = []
    for sel in ("a", "li", "div", "span", "p"):
        try:
            nodes = page.query_selector_all(sel)
        except Exception:
            continue
        for n in nodes[:6000]:
            try:
                t = (n.inner_text() or "").strip()
            except Exception:
                continue
            t = re.sub(r"\s+", " ", t)
            if not (4 <= len(t) <= 30):
                continue
            if BAD.search(t) or NOISE_SENTENCE.search(t):
                continue
            if not JOB_HINT.search(t):
                continue
            titles.append(t)
        if len(titles) >= 400:
            break
    seen: list[str] = []
    for t in titles:
        if t not in seen:
            seen.append(t)
    if seen:
        out["job_titles"] = seen[:150]
    return out


def interact(page, item: dict) -> None:
    for text in item.get("click") or []:
        try:
            loc = page.get_by_text(text, exact=False).first
            loc.click(timeout=4000)
            page.wait_for_timeout(1500)
        except Exception:
            continue
    for _ in range(int(item.get("scroll") or 0)):
        try:
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(700)
        except Exception:
            break


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
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
        )
        for item in targets:
            url = item["url"]
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)
                interact(page, item)
                data = extract(page)
                data.update({"group": item.get("group"), "url": url, "title": page.title()[:60]})
                results[item["id"]] = data
                print(f"OK {item.get('group')} titles={len(data.get('job_titles') or [])} "
                      f"cities={len(data.get('cities') or [])} year={data.get('grad_year')}", flush=True)
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
