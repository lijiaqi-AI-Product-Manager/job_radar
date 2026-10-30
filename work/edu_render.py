"""高校就业网「招聘简章」全量采集 —— 用 Playwright 渲染详情页，拿到简章正文。

为什么必须渲染（docs/DEVELOPMENT.md 铁律 6 的适用条件）：
- 高校就业网的公告正文是**页面 JS 异步注入**的（curl 拿到的是 800 字空壳 + 导航），
  符合「公开页面必须执行 JS 才能拿到内容」；
- 找不到公开 JSON 接口（已实测：无 /api/、无 iframe、无内嵌 state）；
- 页面公开、无需登录、无验证码。
所以这里是铁律 6 允许的渲染场景，且优先级顺序（JSON > SSR > 渲染）已逐条排除。

为什么这条数据合法（calendar/README.md）：
- 高校就业指导中心属教育部 24365 校园招聘体系的公开信息渠道，发布的是**用人单位简章原文**，
  不是牛客/OfferShow/知乎/小红书这类第三方聚合日历（那些在 blocklist 里）；
- 每条都保留公告原始 URL + 发布时间，写日历时可作 official_site 来源的旁证。

产出字段（直接对应日历十项口径）：
- 届次 ← 标题/正文里的「2027届」
- 网申截止 ← 页面的「过期时间」
- 城市 ← 「工作地域：北京市 / 上海市 / …」
- 方向 ← 「职位类别：金融业务人员 / …」+ 正文岗位段
- 投递入口 ← 正文里的网申链接（原文照抄）

用法：
    python3 work/edu_render.py --max-pages 20 --max-detail 120
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar_extract import strip_tags  # noqa: E402

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

BLOCK_MARK = re.compile(r"验证码|安全验证|人机验证|captcha|请先登录|访问受限", re.I)

# 已实测列表结构的站点（分页 URL + 详情链接正则）。只放验证过的。
SITES = [
    {
        "name": "南开大学学生就业指导中心", "short": "南开就业网",
        "first": "https://career.nankai.edu.cn/correcruit/index.html",
        "list": "https://career.nankai.edu.cn/correcruit/index/p/{p}.html",
        "item": re.compile(r'href="(/correcruit/content/id/\d+\.html)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://career.nankai.edu.cn{path}",
        # 实测：南开简章正文需登录，只能拿元数据（地域/类别/学历）
        "has_body": False,
    },
    {
        "name": "西安电子科技大学就业信息网", "short": "西电就业网",
        "first": "https://job.xidian.edu.cn/campus",
        "list": "https://job.xidian.edu.cn/campus",
        "item": re.compile(r'href="(/campus/view/id/\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://job.xidian.edu.cn{path}",
        "has_body": True,
    },
    {
        "name": "广东工业大学学生就业指导中心", "short": "广工就业网",
        "first": "https://career.gdut.edu.cn/campus",
        "list": "https://career.gdut.edu.cn/campus",
        "item": re.compile(r'href="(/campus/view/id/\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://career.gdut.edu.cn{path}",
        "has_body": True,
    },
    {
        "name": "中央民族大学就业信息网", "short": "民大就业网",
        "first": "https://career.muc.edu.cn/front/zpxx.jspa",
        "list": None,
        "item": re.compile(r'href="(/front/zwxx\.jspa\?xqzwId=\d+&zpxxId=\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://career.muc.edu.cn{path}",
        "has_body": True,
    },
    {
        "name": "郑州大学就业创业服务网", "short": "郑大就业网",
        "first": "https://job.zzu.edu.cn/campus",
        "list": "https://job.zzu.edu.cn/campus",
        "item": re.compile(r'href="(/campus/view/id/\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://job.zzu.edu.cn{path}",
        "has_body": True,
    },
    # 以下站点与西电/广工同属一个建站模板（/campus/view/id/N），列表结构一致
    {
        "name": "东北大学秦皇岛分校就业信息网", "short": "东秦就业网",
        "first": "https://job.neuq.edu.cn/campus",
        "list": "https://job.neuq.edu.cn/campus",
        "item": re.compile(r'href="(/campus/view/id/\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://job.neuq.edu.cn{path}",
        "has_body": True,
    },
    {
        "name": "上海电力大学就业信息网", "short": "上电就业网",
        "first": "https://career.shiep.edu.cn/campus",
        "list": "https://career.shiep.edu.cn/campus",
        "item": re.compile(r'href="(/campus/view/id/\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://career.shiep.edu.cn{path}",
        "has_body": True,
    },
    # 2026-10-26 子代理实测补充（同 /campus/view/id 模板，均有正文）：
    # 集美大学正文 4057 字最长，中南大学无「过期时间」但有发布日期与工作城市。
    {
        "name": "集美大学学生就业指导中心", "short": "集大就业网",
        "first": "https://xsjyzd.jmu.edu.cn/campus",
        "list": "https://xsjyzd.jmu.edu.cn/campus",
        "item": re.compile(r'href="(/campus/view/id/\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://xsjyzd.jmu.edu.cn{path}",
        "has_body": True,
    },
    {
        "name": "中南大学就业指导中心", "short": "中南就业网",
        "first": "https://career.csu.edu.cn/campus",
        "list": "https://career.csu.edu.cn/campus",
        "item": re.compile(r'href="(/campus/view/id/\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://career.csu.edu.cn{path}",
        "has_body": True,
    },
    {
        "name": "杭州师范大学就业指导中心", "short": "杭师大就业网",
        "first": "https://career.hznu.edu.cn/campus",
        "list": "https://career.hznu.edu.cn/campus",
        "item": re.compile(r'href="(/campus/view/id/\d+)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://career.hznu.edu.cn{path}",
        "has_body": True,
    },
]

META_FIELDS = {
    "region": re.compile(r"工作(?:地域|地点|城市)[：:]\s*([^\n]{2,120})"),
    "job_cate": re.compile(r"职位类别[：:]\s*([^\n]{2,160})"),
    "degree": re.compile(r"学历要求[：:]\s*([^\n]{2,80})"),
    "expire": re.compile(r"过期时间[：:]\s*(\d{4}-\d{2}-\d{2})"),
    "publish": re.compile(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})"),
    "company_field": re.compile(r"(?:公司名称|单位名称|招聘单位)[：:]\s*([^\n]{2,60})"),
}
RECRUIT_WORDS = re.compile(r"网申|简历|投递|截止|岗位|招聘|专业|要求|面试|笔试|薪资|待遇")
NAV_NOISE = re.compile(r"招聘会|双选会|宣讲会|空中宣讲|就业政策|毕业填报|下载专区|"
                       r"院系介绍|生源信息|招聘指南|联系院系|公示专栏|工作动态|收藏|分享至")


def extract_meta(text: str) -> dict:
    out = {}
    for k, rx in META_FIELDS.items():
        m = rx.search(text)
        if m:
            out[k] = m.group(1).strip()
    return out


def is_body(t: str) -> bool:
    """"像不像简章正文「——招聘语义词占优，且不是侧边栏列表。"""
    if len(t) < 200:
        return False
    return len(RECRUIT_WORDS.findall(t)) > 2 * len(NAV_NOISE.findall(t))


def clean_body(t: str) -> str:
    """砍掉正文前后的站点噪声。

    实测各校页面的正文边界：
    - 前面：站点导航 + 头部，真正正文从「职位描述 / 招聘简章详情 / 公告详情」之后开始；
    - 后面：会拼上「招聘信息」推荐位列表 + 页脚，必须在第一个列表标题处截断，
      否则会把别的公司的城市（比如南开所在的天津）算进本案公司。
    """
    if not t:
        return ""
    # 1) 去头
    m = re.search(r"(职位描述|招聘简章详情|招聘公告详情|简章详情|公告详情|详情)\s*[：:]?\s*\n", t)
    if m and m.end() < len(t) - 300:
        t = t[m.end():]
    # 2) 去尾：第一个「招聘信息/相关招聘/热门职位」列表处截断
    cut = re.search(r"\n(招聘信息|相关招聘|更多招聘|热门职位|推荐招聘|你可能还喜欢)\s*\n", t)
    if cut and cut.start() > 300:
        t = t[:cut.start()]
    # 3) 去固定提示语
    t = re.sub(r"温馨提示：[^\n]{0,120}\n?", "", t)
    t = re.sub(r"收藏\s*-->\s*", "", t)
    t = re.sub(r"浏览次数[：:]\s*\d+", "", t)
    return t.strip()


def pick_body(cands: list[str]) -> str:
    cands = [clean_body(c) for c in cands if len(c) > 200]
    cands = [c for c in cands if len(c) > 200]
    if not cands:
        return ""
    def score(t):
        return (len(RECRUIT_WORDS.findall(t)) - 2 * len(NAV_NOISE.findall(t)), min(len(t), 8000))
    best = max(cands, key=score)
    return best if is_body(best) else ""


def pick_company(title: str, names: list[str]) -> str | None:
    """在一串公司名里挑出与标题最匹配的那一个。

    原实现是 next(n for n in names if n in title)，names 已按长度降序，
    所以命中的是**最长的**那个，这点是对的；但同一个标题里可能同时出现
    母公司和子公司（「中国光大银行武汉分行」），此时应取最长命中，
    以保证 company 尽量具体。这里显式写成 max(len) 把意图固定下来。
    """
    hits = [n for n in names if n in title]
    if not hits:
        return None
    return max(hits, key=len)


def load_names() -> list[str]:
    names = set()
    t = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8"))
    for _s, lst in (t.get("sectors") or {}).items():
        names |= set(lst)
    for f in ("work/entry_pool.jsonl", "work/entry_usable.jsonl"):
        p = ROOT / f
        if p.exists():
            for s in p.read_text(encoding="utf-8").splitlines():
                if s.strip():
                    names.add(json.loads(s)["company"])
    return sorted(names, key=len, reverse=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--max-detail", type=int, default=150)
    ap.add_argument("--out", default="work/edu_hits.jsonl")
    ap.add_argument("--budget-min", type=float, default=180)
    ap.add_argument("--site", default="", help="只跑某个站（按 short 名匹配），调试用")
    args = ap.parse_args()

    names = [n for n in load_names() if len(n) >= 2]
    print(f"match names: {len(names)}", file=sys.stderr)

    outfile = ROOT / args.out
    seen = set()
    if outfile.exists():
        # 采集进程可能被强杀，末行会留半截 JSON。逐行容错读，并顺手把坏行剔掉重写，
        # 否则每个续跑进程都会在同一行崩掉（2026-10-26 实测 6 个进程齐崩）。
        good, bad = [], 0
        for line in outfile.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                good.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
        if bad:
            outfile.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in good),
                               encoding="utf-8")
            print(f"清理损坏行 {bad}", file=sys.stderr)
        seen = {r["url"] for r in good if "url" in r}

    hits, t0 = 0, time.time()
    with sync_playwright() as p, open(outfile, "a", encoding="utf-8") as fh:
        br = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage",
                                                    "--disable-gpu"])
        ctx = br.new_context(user_agent=UA, viewport={"width": 1440, "height": 1200},
                             locale="zh-CN")
        pg = ctx.new_page()
        pg.set_default_timeout(20000)

        for site in SITES:
            if args.site and args.site not in site["short"]:
                continue
            print(f"== {site['short']} ==", file=sys.stderr)
            host = urlsplit(site["first"]).hostname
            last = 0.0
            page_tpl = None
            for pageno in range(1, args.max_pages + 1):
                if site["list"] is None and pageno > 1:
                    break
                # 分页链接在页面里是一长串带站内路由的地址（如
                # /campus/index/do1/job.xidian.edu.cn/domain/xidian/city/page/2），
                # 无法按固定模板拼。做法：第 1 页从 HTML 里发现 "…/page/{n}" 前缀，
                # 之后按该前缀逐页走；发现不了就停在第 1 页（绝不猜 URL）。
                if pageno == 1:
                    url = site["first"]
                elif page_tpl:
                    # 直接翻到第 N 页；失败时退回「顺着首屏给出的下一页链接走」。
                    # 注意：站点分页 URL 里 "city//page/2" 的**双斜杠是服务端要求**，
                    # 压成单斜杠会返回空列表（已实测 p2/p3 各 20 条、与 p1 零重叠）。
                    url = page_tpl.format(p=pageno)
                else:
                    break
                gap = time.monotonic() - last
                if gap < 1.05:
                    time.sleep(1.05 - gap)
                last = time.monotonic()
                html = ""
                for attempt in range(2):
                    try:
                        page = ctx.new_page()
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(1500)
                        html = page.content()
                        page.close()
                        break
                    except Exception as e:
                        msg = f"{type(e).__name__}:{str(e).splitlines()[0][:60]}"
                        try:
                            page.close()
                        except Exception:
                            pass
                        if attempt:
                            print(f"  p{pageno} stop {msg}", file=sys.stderr)
                if not html:
                    break
                if BLOCK_MARK.search(html[:3000]):
                    print(f"  p{pageno} blocked", file=sys.stderr)
                    break
                items, ids = [], set()
                for m in site["item"].finditer(html):
                    path, title = m.group(1), strip_tags(m.group(2)).strip()
                    if not title or len(title) < 6 or path in ids:
                        continue
                    ids.add(path)
                    items.append((path, title))
                if not items:
                    print(f"  p{pageno} no items", file=sys.stderr)
                    break
                # 分页模板只需在第一页发现一次；原先是 `if pageno == 1` 每次必跑，
                # 导致每一页都重复解析、且 page_tpl 被反复覆盖。改成只在还没拿到模板时跑。
                if page_tpl is None:
                    pm = re.search(r'href="([^"]*?/page)/\d+"', html)
                    maxpg = 0
                    for q in re.findall(r'/page/(\d+)', html):
                        maxpg = max(maxpg, int(q))
                    if pm:
                        raw = pm.group(1).rstrip("/") + "/{p}"
                        # 相对路径补成绝对地址即可；路径内部的重复斜杠必须原样保留
                        page_tpl = raw if raw.startswith("http") else "https://" + host + "/" + raw.lstrip("/")
                        print(f"  pager -> {page_tpl} max={maxpg}", file=sys.stderr)
                new = 0
                for path, title in items:
                    hit = pick_company(title, names)
                    if not hit:
                        continue
                    durl = site["detail"].format(path=path)
                    if durl in seen:
                        continue
                    seen.add(durl)
                    gap = time.monotonic() - last
                    if gap < 1.05:
                        time.sleep(1.05 - gap)
                    last = time.monotonic()
                    try:
                        pg.goto(durl, wait_until="domcontentloaded", timeout=25000)
                        try:
                            pg.wait_for_load_state("networkidle", timeout=6000)
                        except Exception:
                            pass
                        pg.wait_for_timeout(800)
                        dhtml = pg.content()
                        dtext = pg.inner_text("body")
                    except Exception:
                        continue
                    if BLOCK_MARK.search(dtext[:2000]):
                        continue
                    body = pick_body([dtext, strip_tags(dhtml)])
                    meta = extract_meta(dtext)
                    # 「工作地域：北京市 / 上海市 / 广东省」→ 城市列表。
                    # 省级名（广东省）说明不了具体城市，转成省→主要城市不严谨，
                    # 所以省级条目原样保留在 region_raw，城市列表只收「XX市」形态。
                    region_raw = meta.get("region", "")
                    cities = []
                    for part in re.split(r"[/、,，\s]+", region_raw):
                        part = part.strip()
                        # 「广东省茂名市」这种「省+市」连写，要先剥掉省级前缀，
                        # 否则会得到「广东省茂名」这种既不是省也不是市的值。
                        part = re.sub(r"^[\u4e00-\u9fa5]{2,7}?(?:省|自治区|特别行政区)", "", part)
                        if part.endswith("市") and 2 <= len(part) <= 6:
                            cities.append(part[:-1])
                    rec = {
                        "site": site["name"], "site_short": site["short"],
                        "company": hit, "title": title, "url": durl,
                        "expire": meta.get("expire"), "publish": meta.get("publish"),
                        # 西电/广工模板会在「过期时间」后面直接打「已过期」标记，
                        # 这是站点自己给的在招状态判断，比我们自己比对日期更权威。
                        "expired_flag": "已过期" in (dtext[:400] if dtext else ""),
                        "region_raw": region_raw, "cities": cities,
                        "job_cate": meta.get("job_cate", ""), "degree": meta.get("degree", ""),
                        "text": body[:60000], "len": len(body),
                        "meta_only": len(body) < 200,
                    }
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    hits += 1
                    new += 1
                    if hits >= args.max_detail:
                        print("detail budget", file=sys.stderr)
                        br.close()
                        return 0
                print(f"  p{pageno}: items={len(items)} new={new}", file=sys.stderr)
                if time.time() - t0 > args.budget_min * 60:
                    print("time budget", file=sys.stderr)
                    br.close()
                    return 0
        br.close()
    print(f"hits={hits} in {time.time()-t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
