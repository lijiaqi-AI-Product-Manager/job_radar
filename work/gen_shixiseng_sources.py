"""把 work/agg_probe_full.jsonl 的命中公司生成 sources/shixiseng.yaml。

命中口径：探针按公司名搜实习僧岗位列表，且列表里出现 `same_company` 归属一致的 cname。
这里只负责「建源」，不保证每家在 crawl 时仍能拉到岗位——那一步由 crawl 验证，
拉不到的公司要回滚（不允许 0 产出挂源凑覆盖率）。

用法：
  python work/gen_shixiseng_sources.py            # 写 sources/shixiseng.yaml
  python work/gen_shixiseng_sources.py --dry-run  # 只打印
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HITS = ROOT / "work" / "agg_probe_full.jsonl"
PINYIN = ROOT / "work" / "pinyin_single.json"
OUT = ROOT / "sources" / "shixiseng.yaml"

HEADER = """\
# 实习僧（shixiseng）公开岗位页。一行一家公司，按公司名搜岗位列表。
# 2026-10-29 新增：聚合渠道（grade C），只收「列表里确实出现本公司岗位」的公司。
# 合规：robots.txt 为空（全放行）；无登录、无签名、无验证码；只读列表 + 详情页；1 req/s。
# 口径：聚合源单独标记 source_kind=aggregator，覆盖率报告里与官方直连分开统计。
defaults:
  adapter: shixiseng
  recruit_types: [intern]
  rate_limit_rps: 1
  params:
    fetch_detail: true
    url_filter: "/intern/[^/]+$"
  compliance:
    checked_on: 2026-10-29
    robots: allowed            # https://www.shixiseng.com/robots.txt 返回 200、0 字节
    terms: "公开岗位检索页与详情页，无需登录；不调用投递/简历/消息接口"
    notes: "聚合渠道 grade C：岗位来自实习僧平台，不等于公司官网直发；1 req/s。"

sources:
"""

BAD = re.compile(r"[^a-z0-9]+")


def slugify(name: str, table: dict[str, str]) -> str:
    out = "".join(
        table.get(ch) or (ch.lower() if ch.isascii() and ch.isalnum() else "") for ch in name
    )
    out = BAD.sub("-", out.lower()).strip("-")
    return out[:40] or "co"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    table = json.loads(PINYIN.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in HITS.read_text(encoding="utf-8").splitlines() if line.strip()]
    hits = [r for r in rows if r.get("hit")]
    seen: set[str] = set()
    used: set[str] = set()
    lines: list[str] = []
    for r in sorted(hits, key=lambda x: x["company"]):
        company = r["company"]
        if company in seen:
            continue
        seen.add(company)
        slug = slugify(company, table)
        base, n = slug, 2
        while slug in used:
            slug = f"{base}-{n}"
            n += 1
        used.add(slug)
        lines.append(
            f"  - id: shixiseng-{slug}\n"
            f"    company: {company}\n"
            f"    params: {{keyword: \"{company}\"}}\n"
        )

    text = HEADER + "".join(lines)
    if args.dry_run:
        print(text[:2000])
        print(f"... {len(lines)} sources")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} with {len(lines)} sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
