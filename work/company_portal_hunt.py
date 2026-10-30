"""逐公司用 360 搜索找「这家公司自己的招聘门户」。

与 so360_harvest.py 的区别：那边是「按行业/省份撒网」发现任意租户，这边是
「拿着 943 家未覆盖目标逐家找」，命中的归属天然就是这家公司（标题仍要核）。

合规：只读搜索结果页，不登录、不破验证；每家公司 1 次查询、间隔 5s；
遇到空页（360 软限流，<20KB）退避 60s 并重新预热 cookie。

用法：
  python work/company_portal_hunt.py [--limit N] [--gap 5]
输出：work/company_portals.jsonl（一行一家，断点续跑）、work/portal_hunted.txt
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

WORK = ROOT / "work"
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
]

PATTERNS = [
    # 注意移动版门户：`cnnc.m.zhiye.com`（360 上很常见），别只认 `<slug>.zhiye.com`
    ("beisen", re.compile(r"https?://([a-z0-9][a-z0-9\-]*)\.(?:m\.)?zhiye\.com")),
    ("hotjob", re.compile(r"https?://([a-z0-9][a-z0-9\-]*)\.hotjob\.cn")),
    ("feishu", re.compile(r"https?://([a-z0-9][a-z0-9\-]*)\.jobs\.feishu\.cn")),
    ("workday", re.compile(r"https?://([a-z0-9][a-z0-9\-]*\.wd\d+\.myworkdayjobs\.com)")),
]
SKIP = {"www", "m", "api", "static", "cdn", "img", "assets", "st", "test", "demo",
        "zhiye", "beisen", "portal-oss", "acdn", "campus", "jobs", "job", "hr", "zp"}


class Fetcher:
    def __init__(self) -> None:
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.ua = random.choice(UAS)
        self.warm = False

    def _h(self) -> dict[str, str]:
        return {"User-Agent": self.ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                "Referer": "https://www.so.com/"}

    def warmup(self) -> None:
        if self.warm:
            return
        try:
            req = urllib.request.Request("https://www.so.com/", headers=self._h())
            with self.opener.open(req, timeout=25) as r:
                r.read(2048)
        except Exception as e:  # noqa: BLE001
            print(f"warmup {type(e).__name__}", file=sys.stderr)
        self.warm = True

    def get(self, url: str) -> bytes | None:
        self.warmup()
        try:
            req = urllib.request.Request(url, headers=self._h())
            with self.opener.open(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            print(f"GET {type(e).__name__}", file=sys.stderr)
            return None


SKIP_SECTORS = {"互联网与软件", "人工智能", "游戏"}


def uncovered(skip_sectors: bool = True) -> list[str]:
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    sector = {}
    for sec, names in (targets.get("sectors") or {}).items():
        for n in names or []:
            sector.setdefault(n, sec)
    companies = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, companies)
    names = [n for n, _ in target_names(targets)]
    out = [n for n in names if not matched.get(n)]
    if skip_sectors:
        out = [n for n in out if sector.get(n) not in SKIP_SECTORS]
    return out


def extract(text: str) -> list[dict]:
    hits: list[dict] = []
    for kind, pat in PATTERNS:
        for m in pat.finditer(text):
            slug = m.group(1).lower()
            if slug in SKIP:
                continue
            hits.append({"kind": kind, "slug": slug, "url": m.group(0)})
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10**9)
    ap.add_argument("--gap", type=float, default=5.0)
    args = ap.parse_args()

    out_path = WORK / "company_portals.jsonl"
    done_path = WORK / "portal_hunted.txt"
    done = set(done_path.read_text(encoding="utf-8").split("\n")) if done_path.exists() else set()
    todo = [n for n in uncovered() if n not in done][: args.limit]
    print(f"todo {len(todo)} (already {len(done)})", flush=True)

    f = Fetcher()
    with open(out_path, "a", encoding="utf-8") as fh, open(done_path, "a", encoding="utf-8") as fd:
        for i, name in enumerate(todo, 1):
            q = f'"{name}" 招聘'
            url = f"https://www.so.com/s?q={urllib.parse.quote(q)}&ie=utf-8"
            body = f.get(url)
            hits: list[dict] = []
            if body and len(body) > 20000:
                hits = extract(urllib.parse.unquote(body.decode("utf-8", "replace")))
            else:
                time.sleep(60)
                f.warm = False
            rec = {"company": name, "query": q, "ok": bool(body and len(body) > 20000), "hits": hits}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            fd.write(name + "\n")
            fd.flush()
            print(f"[{i}/{len(todo)}] {name} hits={len(hits)}", flush=True)
            time.sleep(args.gap)
    print("done", flush=True)


if __name__ == "__main__":
    main()
