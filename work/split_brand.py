"""把 brand_check 的搜索结果拆成「有招聘门户」和「疑似无公开门户」两份证据。

判据（写死在代码里，便于复现）：
  - `titles` 里出现 `{公司核心词}…招聘官网/人才招聘/校园招聘` 模式，且核心词在公司名里出现
    → `has_portal`：说明搜索引擎**索引到过**这家公司的门户标题，值得再跑一次入口反查；
  - 只命中第三方站（智联/前程无忧/BOSS/猎聘/应届生）→ `third_party_only`：
    公司确实在招，但没有自己的公开门户；
  - 什么都没命中 → `no_portal`：连第三方页面标题都没抓到，多半是品牌太小/名字太泛。

注意 `智联校园招聘` 这类片段是第三方站的通用标题，**不能**当作「公司有门户」的证据，
否则会把一大批没有门户的公司误判成「值得再查」，白跑几百个域名。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THIRD = re.compile(r"智联|前程无忧|51job|BOSS直聘|猎聘|应届生求职|大街网|拉勾|实习僧|牛客|"
                   r"看准网|职友集|中华英才|赶集|58同城|丁香人才|医药英才|高校人才网")
GEN = re.compile(r"^(中国|全国|最新|热门|官方|校园|社会|人才)+$")
STRIP = ("股份有限公司", "有限责任公司", "有限公司", "集团股份", "控股集团", "集团公司",
         "集团", "股份", "控股", "公司", "中国区", "总公司")


def core(name: str) -> str:
    n = name
    for s in STRIP:
        n = n[:-len(s)] if n.endswith(s) else n
    return n


def classify(name: str, titles: list[str]) -> tuple[str, str]:
    c = core(name)
    own = []
    for t in titles:
        if THIRD.search(t):
            continue
        if c and c in t and re.search(r"招聘|人才|校园|加入我们", t):
            own.append(t)
    if own:
        return "has_portal", own[0]
    if any(THIRD.search(t) for t in titles):
        return "third_party_only", next(t for t in titles if THIRD.search(t))
    return "no_portal", (titles[0] if titles else "")


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/exp/brand.jsonl")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/exp/brand_split")
    rows = [json.loads(ln) for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip()]
    buckets: dict[str, list[dict]] = {"has_portal": [], "third_party_only": [], "no_portal": []}
    for r in rows:
        kind, ev = classify(r.get("company") or "", r.get("titles") or [])
        buckets[kind].append({"company": r["company"], "evidence": ev,
                              "urls": (r.get("urls") or [])[:6]})
    out.mkdir(parents=True, exist_ok=True)
    for k, v in buckets.items():
        (out / f"{k}.jsonl").write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in v) + "\n", encoding="utf-8")
    (out / "has_portal.txt").write_text(
        "\n".join(x["company"] for x in buckets["has_portal"]) + "\n", encoding="utf-8")
    print(json.dumps({k: len(v) for k, v in buckets.items()}, ensure_ascii=False))
    print("有门户样本：", [x["company"] for x in buckets["has_portal"][:12]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
