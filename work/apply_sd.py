"""把 subdomain.center 探活结果 + hotjob 探活结果写进 sources/*.yaml（零猜测增量）。

去重口径（和 work/apply_intake.py 一致，避免踩过的坑）：
- (adapter, tenant) 已在 sources 里 → 跳过；`beisen_host` 归一成 `beisen`。
- 公司名 core 化后已存在 → 跳过（同一家公司不要两条源）。
- 黑名单 slug 跳过；beisen 门户标题含「多品牌/共享门户/集团门户」的跳过（探活时已滤）。

输出：直接追加到 sources/beisen.yaml、sources/hotjob.yaml、sources/hotjob_legacy.yaml，
行内注释写明来源与岗数，便于日后复核。用法：python work/apply_sd.py [--write]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))

from jobradar.sources import load_sources  # noqa: E402

CORE = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团控股|集团|控股|公司)$")
KIND_NORM = {"beisen_host": "beisen", "beisen_legacy": "beisen"}
BLACK = {
    "careers", "moka", "www", "wecruit", "portal-oss", "campus", "zhiye", "beisen", "admin",
    "test", "demo", "dev", "111", "adminhtk", "alipaycampusk",
}
# 人工复核排除：与已有源同公司但租户名不同（chery1/venustech/hand-china/maccura/szkingdom 已在库），
# 或门户标题无归属（财险/大学/招聘官网）、是北森自建共享门户（北森平台-博瑞电力专场）。
SKIP_SLUG = {"chery", "venustech2", "hand-china1", "maccura1", "szkingdom1",
             "ciczp", "careers", "itcast1", "nrec1", "kuangchi", "ehuatai"}


TAIL = re.compile(r"(招聘官网|招聘网站|招聘门户|招聘中心|招聘平台|人才招聘|校园招聘|社会招聘|招聘|官网|人才)$")
GENERIC = {"业务", "财险", "大学", "招聘", "首页", "校园招聘", "社会招聘", "集团"}
MANUAL = {"uni-president": "统一企业"}


def core(name: str) -> str:
    return CORE.sub("", (name or "").strip())


def clean(name: str) -> str:
    name = re.sub(r"\s+", "", name or "")
    name = re.sub(r"[（(][^)）]*[)）]", "", name)  # 去掉全部括号补充语
    while True:  # 「招聘官网」「人才」这类尾巴可能叠两层
        n = TAIL.sub("", name)
        if n == name:
            break
        name = n
    return name.strip("-_·| ")[:28]


def main() -> None:
    write = "--write" in sys.argv
    only = ""
    if "--only-file" in sys.argv:
        only = sys.argv[sys.argv.index("--only-file") + 1]
    existing = load_sources(ROOT / "sources")
    have_key = set()
    have_co = set()
    for s in existing:
        kind = KIND_NORM.get(s.adapter, s.adapter)
        ten = str(s.params.get("tenant", "")).lower()
        have_key.add((kind, ten))
        have_co.add(core(s.company))

    cands: list[dict] = []
    for fn, kind_default in (
        ("careers_verified.jsonl", None),
        ("sd_hits.jsonl", None),
        ("code_hits.jsonl", None),
        ("wayback_hits.jsonl", None),
        ("hotjob_candidates.jsonl", None),
        ("beisen_customer_hits.jsonl", None),
        ("careers_sd_hits.jsonl", None),
        ("search_verified_clean.jsonl", None),
    ):
        if only and fn != only:
            continue
        p = WORK / fn
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            kind = d.get("platform") or d.get("kind") or kind_default
            if kind == "beisen_host":
                kind = "beisen"
            if kind in ("feishu", "feishu_atsx"):
                continue  # 飞书门户走 work/apply_feishu.py（需 base_url/portal_type 模板）
            slug = str(d.get("slug") or d.get("tenant") or "").lower()
            # 大易新版租户 id 是大写 `SU` + 24 位十六进制，小写化会写成 su…，还原成原样
            if re.fullmatch(r"su[0-9a-f]{20,}", slug):
                slug = "SU" + slug[2:].upper()
            slug_l = slug.lower()
            company = MANUAL.get(slug_l) or clean(d.get("company") or "")
            if not kind or not slug_l or slug_l in BLACK or slug_l in SKIP_SLUG:
                continue
            if int(d.get("count") or 0) <= 0:
                continue  # 没岗的入口不入库（岗数取门户首页 Count）
            if kind == "beisen" and "." in slug_l:
                continue  # 白标域名（如 career.xxx.cn）归属需人工复核，不自动入库
            if kind == "hotjob" and not slug_l.startswith("su"):
                continue  # 新版大易只认 SU 租户 id，品牌名不是租户
            if not company or len(company) < 2 or company in GENERIC:
                continue
            if (kind, slug_l) in have_key or core(company) in have_co:
                continue
            have_key.add((kind, slug_l))
            have_co.add(core(company))
            cands.append({**d, "kind": kind, "slug": slug, "company": company,
                          "src_file": fn})

    beisen = sorted([c for c in cands if c["kind"] == "beisen"], key=lambda x: -int(x.get("count") or 0))
    hotjob = sorted([c for c in cands if c["kind"] == "hotjob"], key=lambda x: -int(x.get("count") or 0))
    legacy = sorted([c for c in cands if c["kind"] == "hotjob_legacy"], key=lambda x: -int(x.get("count") or 0))
    print(f"可入库：beisen {len(beisen)}、hotjob {len(hotjob)}、hotjob_legacy {len(legacy)}")
    for c in beisen[:8]:
        print(f"  beisen  {c['slug']:<18} {c['company']:<16} {c.get('count'):>5}")
    for c in hotjob[:4]:
        print(f"  hotjob  {c['slug']:<22} {c['company']:<14} {c.get('count')}")

    if not write:
        print("（dry-run，加 --write 落盘）")
        return

    if beisen:
        with open(ROOT / "sources" / "beisen.yaml", "a", encoding="utf-8") as fh:
            fh.write("# 2026-10-28 subdomain.center 子域枚举 + 门户 <title> 定归属（逐条探活，岗数取首页 Count）\n")
            for c in beisen:
                fh.write(f"  - {{id: beisen-{c['slug']}, company: {c['company']}, params: {{tenant: {c['slug']}}}}}"
                         f"  # 2026-10-28 新增：{c.get('count')} 岗\n")
    if hotjob:
        with open(ROOT / "sources" / "hotjob.yaml", "a", encoding="utf-8") as fh:
            for c in hotjob:
                fh.write(f"  - id: hotjob-{c['slug'].lower()}\n"
                         f"    company: {c['company']}\n"
                         f"    params: {{host: {c.get('host') or 'wecruit.hotjob.cn'}, tenant: {c['slug']}, page_size: 50}}\n"
                         f"    # 2026-10-28 subdomain.center 枚举 + 首页 SU 租户 id；首页 {c.get('count')} 岗\n")
    if legacy:
        with open(ROOT / "sources" / "hotjob_legacy.yaml", "a", encoding="utf-8") as fh:
            for c in legacy:
                fh.write(f"  - id: hotjob-legacy-{c['slug']}\n"
                         f"    company: {c['company']}\n"
                         f"    params: {{host: {c.get('host') or 'www.hotjob.cn'}, tenant: {c['slug']}, max_pages: 5, page_size: 10}}\n"
                         f"    # 2026-10-28 subdomain.center 枚举；首页 {c.get('count')} 岗\n")

    after = load_sources(ROOT / "sources")
    print(f"写入完成：{len(existing)} → {len(after)} 源、{len({core(s.company) for s in after})} 家公司")


if __name__ == "__main__":
    main()

