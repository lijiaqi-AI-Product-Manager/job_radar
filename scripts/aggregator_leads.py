"""从「招聘资讯聚合页」中提取**官方**招聘站域名（线索发现，不入库）。

为什么要有这个脚本：日历里有 792 个集团完全没有岗位数据，而 `proposed-sources.yaml`
里已经为其中 720 个找到了入口 URL——但其中 45 个指向 `campus.niuqizp.com`，
26 个指向 `app.mokahr.com`。前者是**转载聚合站**（页面自己写着"牛企直聘转载该信息，
仅出于传递更多就业招聘资讯之目的"），后者需要逆向签名。

按 CLAUDE.md 红线，**聚合站的数据一律不入库**。但它页面里通常带着指向公司官方的
链接（例如华侨城那页有 `http://oct.zhaopin.com`）。所以正确做法是：

    聚合页（只读，作线索）→ 提取官方域名 → 交给项目自己的适配器去抓官方站

这个脚本只做第一、二步，输出 `{"公司名": ["候选域名", ...]}`，由人工/后续脚本
核对后再写进 `sources/*.yaml`。它不写数据库、不生成日历条目。

用法：
    uv run python scripts/aggregator_leads.py proposed-sources.yaml out.json [--limit N]
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 与其它脚本一致：诚实爬虫标识，不伪装浏览器
UA = "Mozilla/5.0 (compatible; jobradar-bot/0.1)"

# 聚合站自身及其子域，提取时一律排除
AGGREGATOR_HOSTS = (
    "niuqizp.com", "mokahr.com", "hotjob.cn", "zhiye.com", "italent.cn",
    "mp.weixin.qq.com", "beian.miit.gov.cn", "w3.org", "schema.org",
)
# 明显不是招聘站的域名
SKIP_HOSTS = (
    "qq.com", "weibo.com", "zhihu.com", "bilibili.com", "douyin.com",
    "baidu.com", "google.com", "bing.com", "apple.com", "microsoft.com",
    "cdn.", "static.", "img.", "pic.", "assets.",
)
# 路径/文本里出现这些词，说明是"招聘入口"而不是公司主页
CAREER_HINT = re.compile(r"career|job|zhaopin|zhiye|recruit|campus|hr\.|talent|join", re.I)

LINK_RE = re.compile(r'href="(https?://[^"]+)"', re.I)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_aggregator(host: str) -> bool:
    return any(host == a or host.endswith("." + a) for a in AGGREGATOR_HOSTS)


def _is_skipped(host: str) -> bool:
    if any(host == s or host.endswith("." + s) for s in SKIP_HOSTS if not s.endswith(".")):
        return True
    return bool(re.search(r"^(cdn|static|img|pic|assets)\.", host))


def extract_leads(html: str, page_host: str) -> list[tuple[str, bool]]:
    """返回 [(域名, 是否像招聘入口)]，按"像招聘入口"优先、再按出现次数排序。"""
    counts: dict[str, int] = {}
    hinted: dict[str, bool] = {}
    for url in LINK_RE.findall(html):
        h = _host(url)
        if not h or h == page_host or _is_aggregator(h) or _is_skipped(h):
            continue
        counts[h] = counts.get(h, 0) + 1
        # 路径里带 careers/jobs/zhaopin 之类，或子域本身就叫 campus./job./careers.
        path = urlparse(url).path
        if CAREER_HINT.search(path) or re.match(r"^(careers?|jobs?|zhaopin|campus|hr|talent|recruit)\.", h):
            hinted[h] = True
    ordered = sorted(counts, key=lambda h: (not hinted.get(h, False), -counts[h], h))
    return [(h, hinted.get(h, False)) for h in ordered]


def probe_one(item: tuple[str, str]) -> dict:
    name, url = item
    out = {"company": name, "page": url, "leads": [], "status": None}
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True) as c:
            r = c.get(url)
        out["status"] = r.status_code
        if r.status_code != 200:
            return out
        out["leads"] = [{"host": h, "career_like": c} for h, c in extract_leads(r.text, _host(url))]
    except Exception as e:  # 网络抖动不该让整批失败
        out["status"] = f"error: {type(e).__name__}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("proposed")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    doc = yaml.safe_load(Path(args.proposed).read_text(encoding="utf-8"))
    srcs = doc.get("sources") if isinstance(doc, dict) else doc
    targets = []
    for s in srcs:
        url = (s.get("params") or {}).get("url") or ""
        if _is_aggregator(_host(url)):
            targets.append((s.get("company") or "", url))
    if args.limit:
        targets = targets[: args.limit]
    print(f"待提取 {len(targets)} 个聚合页", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(probe_one, targets))

    # 只保留有候选域名的，按"像招聘入口的候选数"降序
    results.sort(key=lambda r: (-sum(1 for x in r["leads"] if x["career_like"]), r["company"]))
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    ok = sum(1 for r in results if r["leads"])
    hit = sum(1 for r in results if any(x["career_like"] for x in r["leads"]))
    print(f"有候选域名 {ok}/{len(results)}，其中含招聘入口特征的 {hit}", file=sys.stderr)
    for r in results[:20]:
        top = [x["host"] for x in r["leads"][:4]]
        print(f"  {r['company']}: {top}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
