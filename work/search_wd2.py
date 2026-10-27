"""Workday 站点反查 v2：用中文 query 且**不**过滤搜索引擎自己的跳转链。

为什么要 v2：v1 直接用 `{公司} myworkdayjobs` 走必应，59 家 0 命中。查因发现两件事：
  1. 必应对纯英文站点名的中文公司名 query 召回极差，得写成
     `{公司} 招聘 site:myworkdayjobs.com` 或 `{公司} workday 招聘`；
  2. `search_ats.search()` 把 `bing.com` 放进 JUNK，而必应的结果链接如今是
     `cn.bing.com/ck/a?...&u=a1<base64url 目标>` 这种跳转链——过滤 JUNK 等于把
     唯一能拿到真实 URL 的东西也扔了。这里改成从跳转链里解出目标 URL 再过滤。

红线不变：只读公开结果页、同一搜索主机 ≤1 rps、每公司 ≤2 条 query。
"""
from __future__ import annotations

import argparse
import base64
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

WD = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/"
                r"(?:(?:[a-z]{2}-[A-Z]{2})/)?([A-Za-z0-9_\-]+)", re.I)
CK = re.compile(r"[?&]u=a1([A-Za-z0-9_\-]+)", re.I)
ANY = re.compile(r'https?://[^\s"<>\\]+')

_last = 0.0


def throttle() -> None:
    global _last
    gap = 1.05 - (time.time() - _last)
    if gap > 0:
        time.sleep(gap)
    _last = time.time()


def decode_ck(u: str) -> str:
    """`/ck/a?...&u=a1<base64url>` → 真实目标 URL；解不出来返回空串。"""
    m = CK.search(u)
    if not m:
        return ""
    s = m.group(1)
    s += "=" * (-len(s) % 4)
    try:
        raw = base64.urlsafe_b64decode(s)
    except Exception:  # noqa: BLE001
        return ""
    t = raw.decode("utf-8", "ignore")
    return t if t.startswith("http") else ""


def bing(cli: httpx.Client, q: str) -> list[str]:
    throttle()
    try:
        r = cli.get("https://cn.bing.com/search",
                    params={"q": q, "count": "30", "setlang": "zh-CN"})
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    out: list[str] = []
    for u in ANY.findall(r.text):
        cand = decode_ck(u) if "/ck/a" in u else u
        if not cand or any(j in cand for j in JUNK):
            continue
        if cand not in out:
            out.append(cand)
    return out


def sites_of(urls: list[str]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for u in urls:
        m = WD.search(u)
        if m:
            rec = (m.group(1).lower(), m.group(2).lower(), m.group(3))
            if rec not in out:
                out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    names = [x.strip() for x in Path(a.src).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in done]
    print(f"待搜 {len(todo)}", flush=True)
    hit = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli, out.open("a", encoding="utf-8") as f:
        for i, n in enumerate(todo, 1):
            found: list[tuple[str, str, str]] = []
            for q in (f"{n} 招聘 site:myworkdayjobs.com", f"{n} workday 招聘"):
                found += [x for x in sites_of(bing(cli, q)) if x not in found]
                if found:
                    break
            f.write(json.dumps({"company": n, "sites": found}, ensure_ascii=False) + "\n")
            f.flush()
            if found:
                hit += 1
                print(f"HIT {n:14s} {found[0]}", flush=True)
            if i % 20 == 0:
                print(f"... {i}/{len(todo)} 命中 {hit}", flush=True)
    print(f"完成 {len(todo)}，命中 {hit}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
