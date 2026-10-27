"""Workday 站点反查 v3：**拆词**搜（`{中文} myworkdayjobs`），不是 `{公司} site:…`。

前两版都失败的实证（2026-10-27 实测，全部记在 docs/recon/workday.md）：
  v1 `{公司} myworkdayjobs`            → 59 家 0 命中。必应把 `myworkdayjobs` 当噪声词，
                                        结果全是公司官网首页。
  v2 `{公司} 招聘 site:myworkdayjobs.com` → 仍然 0。从数据中心 IP 发出的查询里
                                        **`site:` 被完全忽略**（`site:myworkdayjobs.com
                                        校招` 返回华为校招、腾讯校招、应届生网）。
  v3 本版：`myworkdayjobs` **单独**做主语时必应是认的（返回 workday/jll/abb/path 的真实
     站点），再加一个中文限定词把范围收到中国区。一次 query 能捞 9 条站点，
     比「一家公司一条 query」效率高一个数量级——反查出**站点**之后再按公司名归属。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))
sys.path.insert(0, str(ROOT / "src"))

from search_ats import JUNK  # noqa: E402

from jobradar.adapters.base import USER_AGENT  # noqa: E402

WD = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.(myworkdayjobs|myworkdaysite)\.com/"
                r"(?:(?:[a-z]{2}-[A-Z]{2})/)?([A-Za-z0-9_\-]+)", re.I)

# 中文限定词：把「全球 Workday 站点」收到「与中国有关」。逐词单独跑，命中合集。
QUALIFIERS = [
    "中国", "上海", "北京", "深圳", "广州", "杭州", "苏州", "成都", "武汉", "南京",
    "校招", "校园招聘", "实习", "招聘", "工程师", "China", "Zh China", "Shanghai",
    "Beijing", "Shenzhen", "Hong Kong", "Taiwan",
]

_last = 0.0


def throttle() -> None:
    global _last
    gap = 1.05 - (time.time() - _last)
    if gap > 0:
        time.sleep(gap)
    _last = time.time()


def fetch(cli: httpx.Client, q: str) -> list[str]:
    throttle()
    try:
        r = cli.get("https://cn.bing.com/search", params={"q": q, "count": "30"})
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    out: list[str] = []
    for u in re.findall(r'href="(https?://[^"]+)"', r.text):
        if any(j in u for j in JUNK):
            continue
        if u not in out:
            out.append(u)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--qualifiers", default=",".join(QUALIFIERS))
    a = ap.parse_args()
    quals = [q for q in a.qualifiers.split(",") if q]
    out = Path(a.out)
    seen: set[tuple[str, str, str]] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                seen.add((d["tenant"], d["wd"], d["site"]))
            except Exception:  # noqa: BLE001
                pass
    print(f"已有站点 {len(seen)}，开始 {len(quals)} 条 query", flush=True)
    new = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli, out.open("a", encoding="utf-8") as f:
        for i, q in enumerate(quals, 1):
            urls = fetch(cli, f"myworkdayjobs {q}")
            got = 0
            for u in urls:
                m = WD.search(u)
                if not m:
                    continue
                rec = (m.group(1).lower(), m.group(2).lower(), m.group(4))
                if rec in seen:
                    continue
                seen.add(rec)
                got += 1
                new += 1
                f.write(json.dumps({"tenant": rec[0], "wd": rec[1], "site": rec[2],
                                    "url": u, "query": q}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{i}/{len(quals)}] {q:12s} 新站点 {got}（累计 {new}）", flush=True)
    print(f"完成，新增站点 {new}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
