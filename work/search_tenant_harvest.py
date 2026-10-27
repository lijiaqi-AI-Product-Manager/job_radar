"""从公开搜索结果里捡「招聘门户」——不登录、不逆向、只读搜索结果页。

2026-10-27 实测（本机直连）：
  - 可用：360（`www.so.com/s`）、搜狗（`www.sogou.com/web`）、头条（`so.toutiao.com`）
  - 不可用：Bing（www/cn 都给 ICP 备案页或忽略 site:）、百度（安全验证）、
    DuckDuckGo（首请求 200，之后一律 202 anomaly）、Ecosia（403）、Mojeek（无中文覆盖）
  - crt.sh 只有 `*.zhiye.com` 通配符证书，枚举不出租户

三个可用引擎返回的都是 HTML，目标域名被 URL 编码过（`https%3A%2F%2F360campus.zhiye.com`），
所以先 `unquote()` 整页，再按平台正则扫全页域名。标题不可靠（各引擎结构不同），
归属判断不在这里做 —— 门户自己的 `<title>` 才是准的，交给 verify 那一步。

平台正则：
  *.zhiye.com          → beisen
  *.hotjob.cn          → hotjob
  *.jobs.feishu.cn     → feishu_atsx
  *.myworkdayjobs.com  → workday（少见，先记 host）
Moka 一律丢弃（合规不碰）。

产出 `work/search_tenants.jsonl`：一行一个命中 {platform, slug, query, engine, page}，按查询断点续跑。
节流：每个引擎串行 ≥4s；某引擎退化（<20KB / 202 / 403）就冷却 120s 换下一个引擎。
"""
from __future__ import annotations

import itertools
import json
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "work" / "search_tenants.jsonl"
UA = {
    "sogou": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "toutiao": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "so360": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
ENGINES = {
    "sogou": "https://www.sogou.com/web?query={q}&ie=utf8&page={p}",
    "toutiao": "https://so.toutiao.com/search?keyword={q}&pd=synthesis&page_num={p}",
    "so360": "https://www.so.com/s?q={q}&pn={p}",
}
GAP = 4.0
COOLDOWN = 120.0
PAGES = 3

INDUSTRY = ["互联网", "半导体", "医药", "汽车", "银行", "保险", "证券", "能源", "电力", "化工",
            "装备制造", "地产", "建筑", "消费", "食品", "物流", "通信", "新材料", "环保", "电子"]
PROVINCE = ["北京", "上海", "广东", "江苏", "浙江", "山东", "河南", "四川", "湖北", "湖南",
            "河北", "福建", "安徽", "陕西", "辽宁", "江西", "重庆", "云南", "广西", "山西",
            "内蒙古", "贵州", "新疆", "吉林", "黑龙江", "甘肃", "海南", "宁夏", "青海", "西藏", "天津"]
KIND = ["校园招聘", "社会招聘", "实习生招聘", "秋招", "管培生", "2027届"]

PLATFORMS = [
    ("beisen", re.compile(r"([a-z0-9][a-z0-9\-]{1,30})\.zhiye\.com", re.I)),
    ("hotjob", re.compile(r"([a-z0-9][a-z0-9\-]{1,30})\.hotjob\.cn", re.I)),
    ("feishu_atsx", re.compile(r"([a-z0-9][a-z0-9\-]{1,30})\.jobs\.feishu\.cn", re.I)),
    ("workday", re.compile(r"([a-z0-9][a-z0-9\-]{1,30})\.myworkdayjobs\.com", re.I)),
]
BAD = {"www", "m", "api", "static", "cdn", "portal-oss", "acdn", "campus", "stg", "demo",
       "test", "hr", "job", "jobs", "recruit", "beisen", "zhiye", "www2", "static2"}


def queries() -> list[str]:
    q = [f"site:zhiye.com {k}" for k in KIND]
    q += [f"site:zhiye.com {p} 招聘" for p in PROVINCE]
    q += [f"site:zhiye.com {i} 招聘" for i in INDUSTRY]
    q += [f"site:hotjob.cn {k}" for k in ("校园招聘", "社会招聘", "实习生")]
    q += [f"site:jobs.feishu.cn {k}" for k in ("校园招聘", "社会招聘", "实习生")]
    return q


_locks = {e: threading.Lock() for e in ENGINES}
_last = {e: 0.0 for e in ENGINES}
_cool = {e: 0.0 for e in ENGINES}


def acquire(engine: str) -> None:
    while True:
        with _locks[engine]:
            now = time.time()
            if now < _cool[engine]:
                wait = _cool[engine] - now
            else:
                wait = _last[engine] + GAP - now
                if wait <= 0:
                    _last[engine] = now
                    return
        time.sleep(min(max(wait, 0.05), 2.0))


def scan(text: str) -> list[tuple[str, str]]:
    plain = urllib.parse.unquote(text)
    hits: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for platform, rx in PLATFORMS:
        for m in rx.finditer(plain):
            slug = m.group(1).lower()
            if slug in BAD or len(slug) < 2:
                continue
            key = (platform, slug)
            if key in seen:
                continue
            seen.add(key)
            hits.append(key)
    return hits


def main() -> int:
    qs = queries()
    done: set[str] = set()
    if OUT.exists():
        for ln in OUT.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    done.add(json.loads(ln)["query"])
                except Exception:  # noqa: BLE001
                    pass
    todo = [q for q in qs if q not in done]
    print(f"{len(qs)} 条查询，已完成 {len(done)}，待跑 {len(todo)}", flush=True)
    if not todo:
        return 0
    order = itertools.cycle(ENGINES)
    t0 = time.time()
    found: set[tuple[str, str]] = set()
    with OUT.open("a", encoding="utf-8") as f, httpx.Client(
            headers={"Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html"},
            follow_redirects=True, timeout=25.0, verify=False) as cli:
        for i, q in enumerate(todo, 1):
            engine = next(order)
            got: set[tuple[str, str]] = set()
            for pn in range(1, PAGES + 1):
                acquire(engine)
                url = ENGINES[engine].format(q=urllib.parse.quote(q), p=pn)
                try:
                    r = cli.get(url, headers={"User-Agent": UA[engine]})
                except httpx.HTTPError:
                    _cool[engine] = time.time() + COOLDOWN
                    break
                if r.status_code in (202, 403) or len(r.text) < 20000:
                    _cool[engine] = time.time() + COOLDOWN
                    break
                for platform, slug in scan(r.text):
                    got.add((platform, slug))
                    if (platform, slug) not in found:
                        found.add((platform, slug))
                        f.write(json.dumps({"platform": platform, "slug": slug,
                                            "query": q, "engine": engine, "page": pn},
                                           ensure_ascii=False) + "\n")
                f.flush()
            print(f"[{i}/{len(todo)}] {engine:7s} {q[:30]:30s} +{len(got):2d} 唯一 {len(found)} "
                  f"{time.time() - t0:.0f}s", flush=True)
            time.sleep(0.4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
