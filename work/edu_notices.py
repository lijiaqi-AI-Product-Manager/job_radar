"""高校就业网「招聘简章」全量采集：拿到届次 / 网申时间 / 城市 / 方向 的最权威公开来源。

为什么这条路是合法的（calendar/README.md + CLAUDE.md 铁律 1）：
- 高校就业指导中心（`*.edu.cn`）是**教育部 24365 校园招聘体系**的组成部分，
  公开发布用人单位的招聘简章原文，无需登录、无验证码、无签名接口；
- 页面是服务端渲染的公告正文，属于「官方公告」性质，不是第三方聚合日历
  （牛客/OfferShow/知乎/小红书等在 blocklist 里，高校就业网不在）；
- 每条记录都保留原始公告 URL（作为 `apply_url` 的旁证）与发布时间，
  写进 calendar 时 source.type 用 official_site + 高校就业网名，符合来源白名单。

做法：
1. 对每个已知高校站，翻「招聘简章/招聘信息」列表页（受 --max-pages 限制）；
2. 抽出 (标题, URL)，按公司名（targets 500 + 已有 944 池）做**精确名称匹配**；
3. 命中后抓详情页，抽出正文；
4. 输出 work/edu_hits.jsonl（company / url / title / text / date / site）。

红线：同主机 ≤1 req/s，串行；不点任何交互；遇到验证码即停并标记。

用法：
    python3 work/edu_notices.py --max-pages 30
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar_extract import strip_tags  # noqa: E402

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

BLOCK_MARK = re.compile(r"验证码|安全验证|人机验证|captcha|请先登录|访问受限", re.I)

# 已确认可用的高校就业网「招聘简章列表」入口。
# 只放**实测**过列表结构（分页 URL + 详情链接正则）的站点，不猜。
SITES = [
    {
        "name": "南开大学学生就业指导中心",
        "base": "https://career.nankai.edu.cn",
        "list": "https://career.nankai.edu.cn/correcruit/index/p/{p}.html",
        "first": "https://career.nankai.edu.cn/correcruit/index.html",
        "item": re.compile(r'<a[^>]*href="(/correcruit/content/id/(\d+)\.html)"[^>]*>(.*?)</a>', re.S),
        "detail": "https://career.nankai.edu.cn{path}",
    },
    {
        "name": "西安电子科技大学就业信息网",
        "base": "https://job.xidian.edu.cn",
        "list": "https://job.xidian.edu.cn/campus/index/p/{p}.html",
        "first": "https://job.xidian.edu.cn/campus/index.html",
        "item": re.compile(r'<a[^>]*href="(/campus/view/id/(\d+))"[^>]*>(.*?)</a>', re.S),
        "detail": "https://job.xidian.edu.cn{path}",
    },
    {
        "name": "广东工业大学学生就业指导中心",
        "base": "https://career.gdut.edu.cn",
        "list": "https://career.gdut.edu.cn/campus/index/p/{p}.html",
        "first": "https://career.gdut.edu.cn/campus/index.html",
        "item": re.compile(r'<a[^>]*href="(/campus/view/id/(\d+))"[^>]*>(.*?)</a>', re.S),
        "detail": "https://career.gdut.edu.cn{path}",
    },
]


def load_names() -> list[str]:
    """需要匹配的公司名：targets 500 + 已有池，按长度降序（先匹配长的，避免「京东」抢「京东方」）。"""
    names = set()
    t = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8"))
    for _sec, lst in (t.get("sectors") or {}).items():
        names |= set(lst)
    for f in ("work/entry_pool.jsonl", "work/entry_usable.jsonl"):
        p = ROOT / f
        if p.exists():
            for s in p.read_text(encoding="utf-8").splitlines():
                if s.strip():
                    names.add(json.loads(s)["company"])
    # 用户这轮要求把「全国知名 1500 家 + 各省知名」都过一遍简章，名单里必须带上
    # targets/mega_companies.yaml，否则新扩的公司（尤其省级那批）永远匹配不到。
    mega = ROOT / "targets" / "mega_companies.yaml"
    if mega.exists():
        d = yaml.safe_load(mega.read_text(encoding="utf-8")) or {}
        names |= {str(x) for x in (d.get("national") or [])}
        for lst in (d.get("by_province") or {}).values():
            names |= {str(x) for x in lst}
    return sorted(names, key=len, reverse=True)


def extract(client: httpx.Client, url: str) -> dict:
    try:
        r = client.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=25)
    except Exception as e:
        return {"status": None, "text": "", "html": "", "err": type(e).__name__}
    if r.status_code != 200:
        return {"status": r.status_code, "text": "", "html": "", "err": "http"}
    return {"status": 200, "text": strip_tags(r.text), "html": r.text,
            "blocked": bool(BLOCK_MARK.search(r.text[:3000]))}


def find_date(text: str) -> str | None:
    """公告发布时间 / 过期时间（yyyy-mm-dd）。"""
    for pat in (r"过期时间[：:]\s*(20\d{2})-(\d{2})-(\d{2})",
                r"发布时间[：:]\s*(20\d{2})-(\d{2})-(\d{2})",
                r"(20\d{2})-(\d{2})-(\d{2})\s*(?:\d{2}:\d{2})?"):
        m = re.search(pat, text)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


# 高校就业网常见的结构化元数据（列表页/详情页都有，比正文更可靠）
META_FIELDS = {
    "region": re.compile(r"工作(?:地域|地点|城市)[：:]\s*([^\n]{2,120})"),
    "job_cate": re.compile(r"职位类别[：:]\s*([^\n]{2,160})"),
    "degree": re.compile(r"学历要求[：:]\s*([^\n]{2,80})"),
    "major": re.compile(r"专业要求[：:]\s*([^\n]{2,160})"),
    "expire": re.compile(r"过期时间[：:]\s*(\d{4}-\d{2}-\d{2})"),
}


def extract_meta(text: str) -> dict:
    out = {}
    for k, rx in META_FIELDS.items():
        m = rx.search(text)
        if m:
            out[k] = m.group(1).strip()
    return out


# 正文容器候选：不同高校站用不同 class，全部试一遍，取最长且含招聘语义词的那个
BODY_PATTERNS = [
    re.compile(r'<div class="(?:con|con1|content|article|news_content|zw_content|detail)[^"]*"[^>]*>(.*?)'
               r'(?=<div class="(?:bottom|footer|foot)\b)', re.S),
    re.compile(r'<div[^>]+id="(?:content|article|detail)"[^>]*>(.*?)</div>\s*</div>', re.S),
]
RECRUIT_WORDS = re.compile(r"网申|简历|投递|截止|岗位|招聘|专业|要求|面试|笔试|薪资|待遇")
NAV_NOISE = re.compile(r"招聘会|双选会|宣讲会|空中宣讲|就业政策|毕业填报|下载专区|"
                       r"院系介绍|生源信息|招聘指南|联系院系|公示专栏|工作动态|"
                       r"就业指导|收藏|分享至")


def best_body(html: str) -> str:
    """从详情页 HTML 里挑出「最像招聘简章正文」的一段。

    判据：招聘语义词密度高、导航噪声词少。全是导航的视为无正文（不硬凑）。
    """
    cands = []
    for rx in BODY_PATTERNS:
        for m in rx.finditer(html):
            t = strip_tags(m.group(1))
            if len(t) > 150:
                cands.append(t)
    if not cands:
        return ""

    def score(t: str) -> tuple:
        return (len(RECRUIT_WORDS.findall(t)) - 2 * len(NAV_NOISE.findall(t)), min(len(t), 8000))

    best = max(cands, key=score)
    # 噪声占优 → 说明抓到的是列表/侧边栏，不是简章正文
    if len(NAV_NOISE.findall(best)) * 2 >= len(RECRUIT_WORDS.findall(best)):
        return ""
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--out", default="work/edu_hits.jsonl")
    ap.add_argument("--max-detail", type=int, default=400)
    args = ap.parse_args()

    names = [n for n in load_names() if len(n) >= 2]
    print(f"match names: {len(names)}", file=sys.stderr)
    outfile = ROOT / args.out
    seen_ids = set()
    if outfile.exists():
        for s in outfile.read_text(encoding="utf-8").splitlines():
            if s.strip():
                d = json.loads(s)
                seen_ids.add((d["site"], d["url"]))

    hits = 0
    with httpx.Client(timeout=25, headers={"User-Agent": UA}) as client, \
            open(outfile, "a", encoding="utf-8") as fh:
        for site in SITES:
            print(f"== {site['name']} ==", file=sys.stderr)
            for p in range(1, args.max_pages + 1):
                url = site["first"] if p == 1 else site["list"].format(p=p)
                time.sleep(1.05)
                r = extract(client, url)
                if not r.get("html"):
                    print(f"  p{p} stop: {r.get('status')} {r.get('err')}", file=sys.stderr)
                    break
                items = []
                for m in site["item"].finditer(r["html"]):
                    path, jid, title = m.group(1), m.group(2), strip_tags(m.group(3)).strip()
                    if not title or len(title) < 6:
                        continue
                    if (path, jid) in [(x[0], x[1]) for x in items]:
                        continue
                    items.append((path, jid, title))
                if not items:
                    print(f"  p{p} no items, stop", file=sys.stderr)
                    break
                new = 0
                for path, _jid, title in items:
                    # 精确名称匹配：标题里出现公司名（按长度降序，先长后短）
                    hit = next((n for n in names if n in title), None)
                    if not hit:
                        continue
                    durl = site["detail"].format(path=path)
                    if (site["name"], durl) in seen_ids:
                        continue
                    seen_ids.add((site["name"], durl))
                    time.sleep(1.05)
                    d = extract(client, durl)
                    if d.get("blocked"):
                        print(f"  blocked at {durl}", file=sys.stderr)
                        continue
                    body = d.get("text") or ""
                    core = best_body(d.get("html") or "")
                    meta = extract_meta(body)
                    rec = {
                        "site": site["name"], "company": hit, "title": title, "url": durl,
                        "date": find_date(body) or meta.get("expire"),
                        "expire": meta.get("expire"),
                        "region": meta.get("region", ""),
                        "job_cate": meta.get("job_cate", ""),
                        "degree": meta.get("degree", ""),
                        "text": core[:60000],
                        "len": len(core),
                        "meta_only": len(core) < 150,
                    }
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    hits += 1
                    new += 1
                    if hits >= args.max_detail:
                        print("detail budget reached", file=sys.stderr)
                        return 0
                print(f"  p{p}: items={len(items)} matched_new={new}", file=sys.stderr)
    print(f"hits={hits}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
