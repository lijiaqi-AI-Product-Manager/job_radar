"""搜狗 / 头条搜索 → 招聘平台租户枚举（2026-10-28 实测可用渠道）。

为什么需要它：360 在 15 条查询后整页缩到 3KB 空结果且冷却 1 小时后仍未恢复；
sogou-www 与 so.toutiao 每条约能吐出 9~10 个 zhiye 租户，是目前唯一还能规模化的入口。

请求保持人类节奏：同一引擎相邻请求间隔 5s，整页无结果视为限流并冷却 45s 后重试一次。
输出 work/se_tenants.jsonl（每行 {engine, query, host, url, title}），按 (engine, query) 断点续跑。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUT = WORK / "se_tenants.jsonl"

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
GAP = 5.0
COOLDOWN = 45.0

PLATFORM_PAT = {
    "beisen": re.compile(r"https?://([a-z0-9][a-z0-9\-]{1,40})\.zhiye\.com(/[^\s\"'<>]*)?"),
    "hotjob": re.compile(r"https?://([a-z0-9][a-z0-9\-]{1,40})\.hotjob\.cn(/[^\s\"'<>]*)?"),
    "feishu": re.compile(r"https?://([a-z0-9][a-z0-9\-]{1,40})\.jobs\.feishu\.cn(/[^\s\"'<>]*)?"),
    "tupu360": re.compile(r"https?://([a-z0-9][a-z0-9\-]{1,40})\.careersite\.tupu360\.com(/[^\s\"'<>]*)?"),
    "workday": re.compile(r"https?://([a-z0-9][a-z0-9\-]*\.wd\d+\.myworkdayjobs\.com)(/[a-zA-Z0-9_\-/%]+)?"),
}
SKIP = {
    "www", "m", "api", "static", "assets", "cdn", "portal-oss", "campus", "app", "job", "jobs",
    "recruit", "hr", "career", "careers", "staff", "zp", "zhaopin", "img", "file", "files",
    "download", "upload", "test", "demo", "beisen", "zhiye", "careersite",
}

PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
]
INDUSTRIES = [
    "银行", "证券", "保险", "基金", "能源", "电力", "半导体", "医药", "汽车", "地产",
    "建筑", "钢铁", "化工", "机械", "电子", "通信", "消费", "零售", "物流", "航空",
]


def queries() -> list[dict]:
    qs: list[dict] = []
    # 北森：省份/行业两条轴，交叉太密所以各跑一遍
    for p in PROVINCES:
        qs.append({"engine": "sogou", "q": f"site:zhiye.com {p} 校园招聘"})
    for ind in INDUSTRIES:
        qs.append({"engine": "sogou", "q": f"site:zhiye.com {ind} 招聘"})
    for p in PROVINCES:
        qs.append({"engine": "toutiao", "q": f"site:zhiye.com {p} 招聘"})
    # hotjob：租户少，只跑省份
    for p in ("北京", "上海", "广东", "江苏", "浙江", "山东", "四川", "湖北"):
        qs.append({"engine": "sogou", "q": f"site:hotjob.cn {p} 招聘"})
    return qs


def fetch(client: httpx.Client, engine: str, q: str) -> str:
    if engine == "sogou":
        url = "https://www.sogou.com/web"
        r = client.get(url, params={"query": q, "num": "20"}, timeout=30.0)
    else:
        url = "https://so.toutiao.com/search"
        r = client.get(url, params={"keyword": q, "pd": "synthesis"}, timeout=30.0)
    r.raise_for_status()
    return unquote(r.text)


def title_near(text: str, host: str) -> str:
    i = text.find(host)
    if i < 0:
        return ""
    seg = text[max(0, i - 600) : i + 600]
    m = re.findall(r">([^<>{}]{4,40})<", seg)
    cand = [re.sub(r"\s+", " ", c).strip() for c in m]
    cand = [c for c in cand if any("\u4e00" <= ch <= "\u9fff" for ch in c)]
    return cand[0] if cand else ""


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    qs = queries()
    done: set[str] = set()
    if OUT.exists():
        for ln in OUT.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                done.add(f"{d['engine']}|{d['query']}")
            except Exception:  # noqa: BLE001
                pass
    todo = [x for x in qs if f"{x['engine']}|{x['q']}" not in done]
    if limit:
        todo = todo[:limit]
    print(f"查询 {len(qs)}，未跑 {len(todo)}", flush=True)

    fh = open(OUT, "a", encoding="utf-8")
    with httpx.Client(headers=UA, follow_redirects=True) as client:
        last: dict[str, float] = {}
        for idx, item in enumerate(todo, 1):
            engine, q = item["engine"], item["q"]
            wait = GAP - (time.time() - last.get(engine, 0.0))
            if wait > 0:
                time.sleep(wait)
            text = ""
            for _ in range(2):
                try:
                    text = fetch(client, engine, q)
                except Exception as e:  # noqa: BLE001
                    print(f"  {engine} {q[:28]} 请求失败 {type(e).__name__}", flush=True)
                    time.sleep(3)
                    continue
                if len(text) > 30000:
                    break
                # 整页过短 = 限流/无结果，冷却后再试一次
                time.sleep(COOLDOWN)
            last[engine] = time.time()
            seen: set[tuple[str, str]] = set()
            for platform, pat in PLATFORM_PAT.items():
                for m in pat.finditer(text):
                    host, path = m.group(1), (m.group(2) or "")
                    if host in SKIP or len(host) < 3:
                        continue
                    if (platform, host) in seen:
                        continue
                    seen.add((platform, host))
                    fh.write(
                        json.dumps(
                            {
                                "engine": engine,
                                "query": q,
                                "platform": platform,
                                "host": host,
                                "url": f"https://{host}{path}",
                                "title": title_near(text, host),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            fh.flush()
            print(f"[{idx}/{len(todo)}] {engine} {q[:30]:<32} +{len(seen)}", flush=True)
    fh.close()
    hosts = {(d["platform"], d["host"]) for d in map(json.loads, OUT.read_text(encoding="utf-8").splitlines()) if d}
    print(f"完成：去重租户 {len(hosts)}", flush=True)


if __name__ == "__main__":
    main()
