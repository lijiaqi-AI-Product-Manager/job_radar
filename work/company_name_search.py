"""按公司名反查招聘平台租户：把「目标清单里还没入口的公司」逐家拿去搜。

为什么需要它：2026-10-28 之前，所有租户都是「顺藤摸瓜」找到的——枚举北森子域、
翻 Wayback、搜公开代码。这些方式只能发现「世界上存在哪些租户」，再回头和名单对，
对不上就空着。名单里的公司（万科、立讯、歌尔…）确实有北森/大易门户，但没被任何
枚举渠道扫到，于是覆盖率一直卡在 35%。这条脚本反过来：拿公司名去问搜索引擎
「这家公司 校园招聘」，从结果里把 *.zhiye.com / *.hotjob.cn / *.jobs.feishu.cn 抠出来。

引擎实测（2026-10-28）：
  - Yahoo 日本（search.yahoo.co.jp）：中文站收录好，8 家已知答案里命中 6 家；最稳。
  - 神马 m.sm.cn / 夸克 quark.sm.cn：大部分查询返回空壳页，命中率低，做补充。
  - 360（经 r.jina.ai 转）：限额，本轮用不上。
  - 百度/搜狗/必应：直连全被封（验证码/反爬/索引不覆盖中文站），不碰。

用法：
  python work/company_name_search.py --limit 30           # 试跑
  python work/company_name_search.py                     # 全量（断点续跑）
  python work/company_name_search.py --engines yahoo quark
输出：work/company_search.jsonl，一行一次查询：
  {"company": "立讯精密", "engine": "yahoo", "query": "立讯精密 校园招聘",
   "hosts": ["luxshare.hotjob.cn"], "urls": ["https://luxshare.hotjob.cn/..."]}
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import unquote

import httpx
import yaml

from jobradar.pipeline.calendar import target_names
from jobradar.sources import load_sources

OUT = Path("work/company_search.jsonl")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 三套平台的租户主机；平台自身主机（www/portal-oss/job/beisen）不是租户，直接丢。
HOST_RE = re.compile(
    r"([a-z0-9][a-z0-9-]{1,40})\.(zhiye\.com|hotjob\.cn|jobs\.feishu\.cn)", re.I
)
PLATFORM_HOSTS = {
    "www", "job", "jobs", "portal-oss", "beisen", "zhiye", "hotjob", "acdn", "m", "api",
}
# 招聘页常见路径，用来在结果 URL 里挑「更像门户」的那几个
CAREER_WORDS = ("campus", "job", "career", "zhaopin", "recruit", "position", "join")

ENGINES: dict[str, tuple[str, str]] = {
    "yahoo": ("https://search.yahoo.co.jp/search", "p"),
    "quark": ("https://quark.sm.cn/s", "q"),
}
PATTERNS = ("{n} 校园招聘", "{n} 招聘 官网")


def core(name: str) -> str:
    return re.sub(
        r"(股份有限公司|有限责任公司|有限公司|集团|控股|中国|股份|总公司|公司)$", "", name
    ).strip()


def uncovered() -> list[str]:
    """目标清单里还没有任何源的公司（按 core 名比对，和覆盖率报表同一口径）。"""
    targets = yaml.safe_load(Path("targets/top_companies.yaml").read_text(encoding="utf-8"))
    names = [name for name, _ in target_names(targets)]
    covered = {core(src.company) for src in load_sources("sources")}
    out, seen = [], set()
    for name in names:
        key = core(name)
        if key in covered or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def done_keys(path: Path) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    if not path.exists():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        keys.add((row.get("company", ""), row.get("engine", ""), row.get("query", "")))
    return keys


def parse_hosts(text: str) -> tuple[list[str], list[str]]:
    """从结果页里抠租户主机 + 对应的完整 URL。"""
    text = unquote(text)
    hosts: list[str] = []
    urls: list[str] = []
    for m in HOST_RE.finditer(text):
        tenant, suffix = m.group(1).lower(), m.group(2).lower()
        if tenant in PLATFORM_HOSTS:
            continue
        host = f"{tenant}.{suffix}"
        if host not in hosts:
            hosts.append(host)
    for m in re.finditer(r"https?://[a-z0-9.-]+\.(?:zhiye\.com|hotjob\.cn|jobs\.feishu\.cn)[^\s\"'<>]*", text, re.I):
        url = m.group(0)
        if url not in urls:
            urls.append(url)
    urls.sort(key=lambda u: 0 if any(w in u.lower() for w in CAREER_WORDS) else 1)
    return hosts[:12], urls[:8]


def search(client: httpx.Client, engine: str, query: str) -> tuple[int, str, str | None]:
    url, key = ENGINES[engine]
    try:
        resp = client.get(url, params={key: query})
        return resp.status_code, resp.text, None
    except Exception as exc:  # noqa: BLE001 - 网络异常一律记在行里
        return 0, "", f"{type(exc).__name__}: {str(exc)[:120]}"


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--engines", nargs="+", default=["yahoo"])
    ap.add_argument("--pause", type=float, default=2.4, help="同一引擎两次查询的间隔（秒）")
    ap.add_argument("--names", help="用文件里的公司名（每行一个）代替自动算缺口")
    args = ap.parse_args(argv)

    names = (
        [ln.strip() for ln in Path(args.names).read_text(encoding="utf-8").splitlines() if ln.strip()]
        if args.names
        else uncovered()
    )
    if args.limit:
        names = names[: args.limit]
    done = done_keys(OUT)
    tasks = [
        (name, eng, pat.format(n=name))
        for name in names
        for pat in PATTERNS
        for eng in args.engines
        if (name, eng, pat.format(n=name)) not in done
    ]
    print(f"公司 {len(names)}，待查 {len(tasks)}（已完成 {len(done)}）", flush=True)
    if not tasks:
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    hits = 0
    errors = 0
    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}, timeout=40, follow_redirects=True
    ) as client, OUT.open("a", encoding="utf-8") as fh:
        for i, (name, engine, query) in enumerate(tasks, 1):
            status, text, err = search(client, engine, query)
            hosts, urls = parse_hosts(text) if text else ([], [])
            row = {
                "company": name,
                "engine": engine,
                "query": query,
                "status": status,
                "hosts": hosts,
                "urls": urls,
            }
            if err:
                row["error"] = err
                errors += 1
            elif len(text) < 3000:
                row["error"] = "thin-page"
                errors += 1
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if hosts:
                hits += 1
            if i % 25 == 0:
                print(
                    f"  {i}/{len(tasks)} 命中 {hits} 薄页/异常 {errors} 最新 {name} {hosts[:3]}",
                    flush=True,
                )
            time.sleep(args.pause + random.random() * 0.6)
    print(f"完成：{len(tasks)} 次查询，命中 {hits}，薄页/异常 {errors} -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
