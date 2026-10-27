"""360 搜索 → 招聘门户域名 harvest（带 Cookie、按 pn 翻页、断点续跑）。

背景（2026-10-27 实测）：
- www.so.com 是唯一在「无 key、无登录」下仍能稳定返回站点级结果的搜索引擎；
  bing/baidu/搜狗(桌面)/google 都需要验证或直接 0 结果。
- 必须先访问一次 https://www.so.com/ 拿到 _S / QiHooGUID cookie，否则直接打 /s 会返回空页。
- 每页约 7 个目标域名，pn=1..5 翻页可拿到更多；间隔 2s、遇到空页退避 90s。

输出：work/so360_hosts.txt（每行 `kind\thost`，去重）、work/so360_done.txt（已完成的 query）
"""
from __future__ import annotations

import http.cookiejar
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
]

PATTERNS = [
    ("beisen", re.compile(r"([a-z0-9][a-z0-9\-]*)\.zhiye\.com")),
    ("hotjob", re.compile(r"([a-z0-9][a-z0-9\-]*)\.hotjob\.cn")),
    ("feishu", re.compile(r"([a-z0-9][a-z0-9\-]*)\.jobs\.feishu\.cn")),
    ("workday", re.compile(r"([a-z0-9][a-z0-9\-]*\.wd\d+\.myworkdayjobs\.com)")),
    ("tupu360", re.compile(r"([a-z0-9][a-z0-9\-]*)\.careersite\.tupu360\.com")),
]

SKIP_SLUGS = {
    "www", "m", "api", "static", "cdn", "img", "assets", "st", "stg", "test", "demo",
    "zhiye", "beisen", "portal-oss", "acdn", "campus", "jobs", "job", "hr", "zp",
}

INDUSTRIES = [
    "银行", "证券", "保险", "基金", "信托", "汽车", "新能源", "半导体", "芯片", "医药",
    "医疗", "地产", "建筑", "建材", "钢铁", "有色", "化工", "电力", "能源", "煤炭",
    "食品", "饮料", "乳业", "白酒", "家电", "电子", "通信", "运营商", "软件", "互联网",
    "游戏", "传媒", "物流", "航空", "机场", "港口", "铁路", "地铁", "机械", "重工",
    "军工", "航天", "船舶", "环保", "零售", "商贸", "纺织", "服装", "造纸", "农业",
]

PROVINCES = [
    "北京", "上海", "天津", "重庆", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
    "广西", "海南", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
]

PLATFORM_QUERIES = {
    "beisen": [
        "site:zhiye.com 校园招聘", "site:zhiye.com 社会招聘", "site:zhiye.com 实习生招聘",
        "site:zhiye.com 2027届", "site:zhiye.com 秋招", "site:zhiye.com 春招",
        "site:zhiye.com 招聘官网", "site:zhiye.com 人才招聘",
    ],
    "hotjob": [
        "site:hotjob.cn 校园招聘", "site:hotjob.cn 社会招聘", "site:hotjob.cn 招聘",
        "site:hotjob.cn 实习生", "site:hotjob.cn wecruit",
    ],
    "feishu": [
        "site:jobs.feishu.cn 校园招聘", "site:jobs.feishu.cn 社会招聘",
        "site:jobs.feishu.cn 招聘", "site:jobs.feishu.cn 实习生",
    ],
    "workday": [
        "site:myworkdayjobs.com 校园招聘 中国", "site:myworkdayjobs.com zh-CN 招聘",
    ],
}


def build_queries() -> list[str]:
    qs: list[str] = []
    for phrases in PLATFORM_QUERIES.values():
        qs.extend(phrases)
    for ind in INDUSTRIES:
        qs.append(f"site:zhiye.com {ind} 招聘")
    for prov in PROVINCES:
        qs.append(f"site:zhiye.com {prov} 招聘")
        qs.append(f"site:zhiye.com {prov} 校园招聘")
    # 去重保序
    seen: set[str] = set()
    out = []
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


class Fetcher:
    def __init__(self) -> None:
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.ua = random.choice(UAS)
        self.home_done = False

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Referer": "https://www.so.com/",
        }

    def warmup(self) -> None:
        if self.home_done:
            return
        try:
            req = urllib.request.Request("https://www.so.com/", headers=self._headers())
            with self.opener.open(req, timeout=25) as resp:
                resp.read(4096)
        except Exception as exc:  # noqa: BLE001 - 预热失败不致命，后续请求自己会重试
            print(f"warmup failed: {type(exc).__name__}", file=sys.stderr)
        self.home_done = True

    def get(self, url: str, timeout: int = 30) -> bytes | None:
        self.warmup()
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            print(f"GET {url} -> {type(exc).__name__}", file=sys.stderr)
            return None


def extract(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for kind, pat in PATTERNS:
        for m in pat.finditer(text):
            slug = m.group(1).lower()
            if slug in SKIP_SLUGS:
                continue
            hits.append((kind, m.group(1).lower() if kind != "workday" else m.group(1)))
    return hits


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    hosts_path = WORK / "so360_hosts.txt"
    done_path = WORK / "so360_done.txt"
    done = set(done_path.read_text(encoding="utf-8").split()) if done_path.exists() else set()
    seen: set[tuple[str, str]] = set()
    if hosts_path.exists():
        for line in hosts_path.read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                k, h = line.split("\t", 1)
                seen.add((k, h))

    f = Fetcher()
    queries = [q for q in build_queries() if q not in done][:limit]
    print(f"queries to run: {len(queries)}", flush=True)
    new_total = 0
    with open(hosts_path, "a", encoding="utf-8") as fh, open(done_path, "a", encoding="utf-8") as fdone:
        for idx, q in enumerate(queries, 1):
            got = 0
            for pn in range(1, pages + 1):
                url = f"https://www.so.com/s?q={urllib.parse.quote(q)}&pn={pn}&ie=utf-8"
                body = f.get(url)
                if not body or len(body) < 20000:
                    time.sleep(90)
                    f.home_done = False
                    continue
                text = urllib.parse.unquote(body.decode("utf-8", "replace"))
                hits = extract(text)
                for kind, host in hits:
                    if (kind, host) in seen:
                        continue
                    seen.add((kind, host))
                    fh.write(f"{kind}\t{host}\n")
                    fh.flush()
                    got += 1
                    new_total += 1
                time.sleep(2.0)
            fdone.write(q + "\n")
            fdone.flush()
            print(f"[{idx}/{len(queries)}] {q} +{got} total={len(seen)}", flush=True)
            time.sleep(1.5)
    print(f"done new_total={new_total} uniq={len(seen)}", flush=True)


if __name__ == "__main__":
    main()
