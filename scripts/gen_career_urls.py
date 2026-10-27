"""从「公司名 + 已知域名」推出可能的招聘入口 URL，交给 detect_ats.py 识别平台。

覆盖率瓶颈是「这家公司用哪个 ATS」，而找 ATS 的第一步是**找到它的招聘页**。
人工一家家点 835 家不现实，本脚本把这件事做成可复现的批量生成：

  ① 有已知域名 → 直接试 `careers.` / `job.` / `zhaopin.` / `hr.` 等子域；
  ② 有英文品牌名 → 试 `{brand}careers.com` / `{brand}jobs.com` / `careers.{brand}.com`；
  ③ 都没有 → 不出候选（宁可不猜，也不去撞别人的域名）。

**只生成候选，不发请求**。真正的探测在 detect_ats.py，它读 robots 之外只发一次 GET。
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 招聘站的常见子域前缀（国内 + 外企），按命中率排序
SUBDOMAINS = ("careers", "career", "job", "jobs", "zhaopin", "recruit", "hr", "talent",
              "join", "apply", "campus", "hire", "wecruit")


def load_blocked(path: str) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def english_brand(row: dict) -> str:
    """`brand` 字段是英文品牌名；没有就返回空。"""
    b = (row.get("brand") or "").strip()
    # 去掉「中国 / China / 集团」这类后缀，得到裸品牌
    b = re.sub(r"(中国|集团|（中国）|\(中国\)|China|Inc\.?|Ltd\.?|Co\.?)$", "", b, flags=re.I).strip()
    return b


def domain_of(brand: str) -> str:
    """把品牌名压成一个可达的域名主干：只留 a-z0-9，`Coca-Cola` → `cocacola`。"""
    return re.sub(r"[^a-z0-9]", "", brand.lower())


def candidates(row: dict, limit: int = 6) -> list[str]:
    out: list[str] = []

    def add(u: str) -> None:
        u = u.strip().lower()
        if u and u not in out:
            out.append(u)

    brand = english_brand(row)
    d = domain_of(brand) if brand else ""
    known = (row.get("domain") or "").strip().lower()

    if known:
        # 已知主域名：只试子域，不动主站的路径（主站路径各家不同，猜了也是 404）
        for sub in SUBDOMAINS:
            add(f"https://{sub}.{known}")
    if d and len(d) >= 3:
        add(f"https://careers.{d}.com")
        add(f"https://{d}careers.com")
        add(f"https://{d}jobs.com")
        add(f"https://jobs.{d}.com")
    return out[:limit]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="blocked.jsonl")
    ap.add_argument("--out", help="候选 URL 列表（一行一个，去重）")
    ap.add_argument("--map", help="URL -> 公司名 的映射 JSON")
    args = ap.parse_args()

    rows = load_blocked(args.src)
    seen: set[str] = set()
    urls: list[str] = []
    mapping: dict[str, str] = {}
    for r in rows:
        for u in candidates(r):
            if u in seen:
                continue
            seen.add(u)
            mapping[u] = r.get("company", "")
            urls.append(u)

    text = "\n".join(urls) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{len(urls)} 个候选 -> {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    if args.map:
        Path(args.map).write_text(json.dumps(mapping, ensure_ascii=False, indent=0), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
