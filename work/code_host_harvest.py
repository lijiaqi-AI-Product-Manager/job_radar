"""从公开代码搜索里挖招聘门户子域（Sourcegraph 公开实例，匿名可用）。

为什么走这条路：招聘平台的租户名都是猜不出来的拼音/哈希，而公司自己的爬虫、导航站、
采集脚本经常把 `xxx.zhiye.com`、`xxx.jobs.feishu.cn` 这类完整域名写死在代码和配置里。
公开代码搜索因此能一次问出成百上千个真实租户，比逐个猜 `{拼音}.zhiye.com` 准得多。

用法：
    python work/code_host_harvest.py            # 全部平台
    python work/code_host_harvest.py zhiye      # 只跑一个

输出：
    work/code_hosts.json   {"zhiye.com": [...], "hotjob.cn": [...], "jobs.feishu.cn": [...], "workday": [...]}
    work/code_hosts.jsonl  每行 {platform, host, site, query}
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

WORK = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (compatible; jobradar-research/1.0)", "Accept": "text/event-stream"}
ENDPOINT = "https://sourcegraph.com/.api/search/stream"

# platform → (域名后缀, 提取正则, 额外查询词)
PLATFORMS = {
    "zhiye.com":        ("zhiye.com",        r"\b([a-z0-9][a-z0-9-]{0,40})\.zhiye\.com\b", ["zhiye.com/campus", "zhiye.com/alljob", "zhiye.com/social", "zhiye.com/portal"]),
    "hotjob.cn":        ("hotjob.cn",        r"\b([a-z0-9][a-z0-9-]{0,40})\.hotjob\.cn\b", ["hotjob.cn/wt", "wecruit.hotjob.cn/SU"]),
    "jobs.feishu.cn":   ("jobs.feishu.cn",   r"\b([a-z0-9][a-z0-9-]{0,40})\.jobs\.feishu\.cn\b", ["jobs.feishu.cn/api/v1", "jobs.feishu.cn/campus"]),
}
WORKDAY = r"\b([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)(/[A-Za-z0-9_-]{2,40})?"

# 代码里的模板/占位/基础设施域名，不是租户
NOISE = {"a", "b", "x", "y", "z", "ab", "alias", "acme", "ey", "www", "m", "api", "app",
         "admin", "test", "demo", "static", "cdn", "img", "assets", "portal", "sso", "login",
         "careers", "job", "jobs", "hr", "campus", "recruit", "zhiye", "beisen", "hotjob",
         "feishu", "localhost", "example", "foo", "bar", "your-tenant", "tenant", "yourcompany"}
BAD_SUFFIX = re.compile(r"^(\d+\.\d+\.\d+\.\d+|.*\.(js|json|py|md|yml|yaml|txt|html?))$", re.I)


def query(q: str, timeout: float = 120.0) -> str:
    with httpx.Client(timeout=timeout, headers=UA, follow_redirects=True) as c:
        with c.stream("GET", ENDPOINT, params={"q": q, "v": "V3"}) as r:
            r.raise_for_status()
            return "".join(r.iter_text())


def harvest(platform: str, tries: int = 2) -> tuple[list[tuple[str, str]], list[str]]:
    suffix, pat, extra = PLATFORMS[platform]
    found: dict[str, str] = {}  # host → query
    queries = [f"context:global {suffix} count:1000"] + [f"context:global {e} count:1000" for e in extra]
    for q in queries:
        for attempt in range(tries):
            try:
                text = query(q)
                break
            except (httpx.HTTPError, httpx.StreamError) as exc:  # 公开实例偶尔 502/超时
                print(f"  ! {q} 第 {attempt + 1} 次失败：{type(exc).__name__}", flush=True)
                time.sleep(3 * (attempt + 1))
        else:
            continue
        hosts = set()
        for m in re.finditer(pat, text):
            h = m.group(0).lower()
            if "{" in h or "}" in h or "$" in h:
                continue
            hosts.add(h)
        added = 0
        for h in hosts:
            sub = h.split(".")[0]
            if sub in NOISE or BAD_SUFFIX.match(h):
                continue
            if h not in found:
                found[h] = q
                added += 1
        print(f"  {q}: 页面 {len(text) // 1024}KB，命中域名 {len(hosts)}，新增 {added}", flush=True)
        time.sleep(2.0)
    return [(h, q) for h, q in found.items()], queries


def harvest_workday(tries: int = 2) -> list[tuple[str, str]]:
    q = "context:global myworkdayjobs.com count:1000"
    for attempt in range(tries):
        try:
            text = query(q)
            break
        except (httpx.HTTPError, httpx.StreamError):
            time.sleep(3 * (attempt + 1))
    else:
        return []
    out = {}
    for m in re.finditer(WORKDAY, text):
        host, site = m.group(1).lower(), (m.group(2) or "").lower().lstrip("/")
        if "$" in host or "{" in host:
            continue
        out.setdefault(host, "")
        if site and not out[host]:
            out[host] = site
    print(f"  workday: 页面 {len(text) // 1024}KB，命中主机 {len(out)}", flush=True)
    return sorted(out.items())


def main() -> None:
    want = sys.argv[1:] or list(PLATFORMS) + ["workday"]
    result: dict[str, list[str]] = {}
    rows: list[dict] = []
    for platform in want:
        if platform == "workday":
            pairs = harvest_workday()
            result["workday"] = [h for h, _ in pairs]
            rows += [{"platform": "workday", "host": h, "site": site, "query": "myworkdayjobs.com"} for h, site in pairs]
            continue
        if platform not in PLATFORMS:
            print(f"跳过未知平台 {platform}")
            continue
        pairs, _ = harvest(platform)
        result[platform] = sorted(h for h, _ in pairs)
        rows += [{"platform": platform, "host": h, "site": "", "query": q} for h, q in pairs]

    (WORK / "code_hosts.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(WORK / "code_hosts.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("总计：" + "，".join(f"{k} {len(v)}" for k, v in result.items()), flush=True)


if __name__ == "__main__":
    main()
