"""把验证过的候选租户整理成可入库的清单（只产出提案，不直接改 sources/）。

输入：work/verified_new_sources.jsonl（verify_tenants_found.py 产出）
      work/search_tenants.jsonl（搜索引擎 harvest 的原始域名，可选增量）
输出：work/intake_proposal.jsonl  每行 {kind, slug, company, proposed_name, count, title, action, why}
      work/intake_review.txt      人工过目用的表格（按 count 降序）

判定规则：
- 已在 sources/*.yaml 里出现过的（adapter + tenant/host/base_url 三元组）→ action=skip, why=duplicate
- 公司名已在 companies.jsonl 或 sources 里有源的 → action=review, why=company-conflict（同名不同站，需要人工定归属）
- score < 0.6 且标题清洗后为空 → action=review, why=name-unresolved
- 其余 → action=add
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
WORK = ROOT / "work"

JUNK_NAMES = {"招聘", "官网", "门户", "首页", "公司", "集团", "校园招聘", "社会招聘", "人才", "招聘中心"}

JUNK_SLUGS = {
    "www", "wecruit", "portal-oss", "acdn", "campus", "m", "api", "static",
    "job", "jobs", "hr", "zp", "demo", "test", "beisen", "zhiye", "recruit",
    "app", "login", "index", "home", "sso", "passport", "mail", "oa",
}

# 标题里可去掉的后缀（从右往左反复剥）
TITLE_TAIL = [
    "招聘门户网站", "招聘门户网", "招聘官网", "人才招聘官网", "招聘网站", "招聘网",
    "校园招聘官网", "校园招聘网", "社会招聘官网", "社会招聘网", "实习生招聘",
    "校园招聘", "社会招聘", "人才招聘", "招聘系统", "招聘平台", "招聘中心",
    "招聘", "首页", "官网", "官方网站", "网站", "门户",
]
CORP_TAIL = [
    "股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "控股集团",
    "集团", "控股", "公司",
]


def clean_name(title: str | None) -> str:
    if not title:
        return ""
    name = title.strip()
    name = re.split(r"[—\-|｜·:：]", name)[0].strip()
    changed = True
    while changed:
        changed = False
        for tail in TITLE_TAIL:
            if name.endswith(tail) and len(name) > len(tail):
                name = name[: -len(tail)].strip()
                changed = True
    for tail in CORP_TAIL:
        if name.endswith(tail) and len(name) > len(tail) + 1:
            name = name[: -len(tail)].strip()
            break
    return name.strip(" 　()（）[]【】")


def _entries(text: str) -> list[str]:
    """把 yaml 文本切成「源条目」块：以 `- ` 开头的行开启新块（紧凑单行也算一块）。"""
    blocks: list[str] = []
    cur: list[str] = []
    for line in text.splitlines():
        if re.match(r"^sources:\s*$", line):
            continue
        m = re.match(r"^\s*-\s", line)
        if m:
            if cur:
                blocks.append("\n".join(cur))
            cur = [line.strip()]
        elif cur and not re.match(r"^\S", line):
            cur.append(line.strip())
        elif cur:
            blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))
    if blocks:
        return blocks
    # 单公司文件（没有 sources: 列表，靠顶层 id/company 识别）
    return [text]


def load_existing() -> tuple[set[tuple[str, str]], set[str], set[tuple[str, str]]]:
    """返回（(kind, 站点 key) 集合, 已有源的公司名集合, (kind, 公司名) 集合）。"""
    keys: set[tuple[str, str]] = set()
    companies: set[str] = set()
    company_keys: set[tuple[str, str]] = set()
    for path in sorted(SOURCES.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^\s*adapter:\s*([\w_]+)", text, re.M)
        adapter = m.group(1) if m else ""
        for block in _entries(text):
            kind = adapter
            am = re.search(r"adapter:\s*([\w_]+)", block)
            if am:
                kind = am.group(1)
            cm = re.search(r"company:\s*([^,}\n]+)", block)
            company = cm.group(1).strip() if cm else ""
            tm = re.search(r"tenant:\s*([\w.\-]+)", block)
            hm = re.search(r"host:\s*([\w.\-]+)", block)
            bm = re.search(r"base_url:\s*\"?https?://([\w.\-]+)", block)
            bm2 = re.search(r"base:\s*https?://([\w.\-]+)", block)
            if company:
                companies.add(company)
                if kind:
                    company_keys.add((kind, company))
            if kind == "beisen":
                if tm:
                    keys.add(("beisen", tm.group(1)))
                if hm:
                    keys.add(("beisen_host", hm.group(1)))
            elif kind in {"hotjob", "hotjob_legacy"}:
                if hm:
                    keys.add((kind, hm.group(1)))
            elif kind == "feishu_atsx" and bm:
                keys.add(("feishu", bm.group(1).split(".")[0]))
            elif kind == "tupu360" and bm2:
                keys.add(("tupu360", bm2.group(1)))
    return keys, companies, company_keys


def main() -> None:
    existing_keys, existing_companies, existing_company_keys = load_existing()
    with open(WORK / "verified_new_sources.jsonl", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]

    out = []
    seen: set[tuple[str, str]] = set()
    seen_company: dict[tuple[str, str], str] = {}
    for row in rows:
        kind = row.get("kind", "")
        slug = (row.get("slug") or "").strip().lower()
        count = int(row.get("count") or 0)
        title = row.get("title") or ""
        company = row.get("company") or ""
        score = float(row.get("score") or 0)
        if kind == "beisen_host":
            # params 里带 host；key 用完整域名
            params = row.get("params") or {}
            host = (params.get("host") or slug or "").lower()
            key = ("beisen_host", host)
        else:
            key = (kind, slug)

        action, why = "add", ""
        if slug in JUNK_SLUGS or not slug:
            action, why = "skip", "junk-slug"
        elif count <= 0 and kind in ("beisen", "beisen_host"):
            action, why = "skip", "no-jobs"
        elif count <= 0 and not (score >= 0.9 and company):
            # feishu/hotjob 拿不到岗位数（count=None）：只有标题命中到公司名才收，否则没归属证据
            action, why = "skip", "no-count-unattributed"
        elif key in existing_keys:
            action, why = "skip", "duplicate"
        elif key in seen:
            action, why = "skip", "dup-in-batch"
        else:
            if score < 0.6 or not company:
                cleaned = clean_name(title)
                company = cleaned or company
            if company in JUNK_NAMES or len(company) < 2:
                action, why = "review", "name-unresolved"
            elif (kind, company) in seen_company:
                action, why = "skip", f"company-dup-with:{seen_company[(kind, company)]}"
            elif (kind, company) in existing_company_keys:
                action, why = "skip", "company-already-has-same-adapter"
        seen.add(key)
        if action == "add":
            seen_company[(kind, company)] = slug
        out.append(
            {
                "kind": kind,
                "slug": slug,
                "company": company,
                "proposed_name": company or clean_name(title),
                "count": count,
                "title": title,
                "score": score,
                "params": row.get("params") or {},
                "action": action,
                "why": why,
            }
        )

    out.sort(key=lambda r: (-r["count"], r["slug"]))
    with open(WORK / "intake_proposal.jsonl", "w", encoding="utf-8") as fh:
        for row in out:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    add = [r for r in out if r["action"] == "add"]
    review = [r for r in out if r["action"] == "review"]
    skip = [r for r in out if r["action"] == "skip"]
    lines = [f"总计 {len(out)} 条：可入库 {len(add)}，待人工 {len(review)}，跳过 {len(skip)}", ""]
    for label, group in (("== 可入库 ==", add), ("== 待人工 ==", review)):
        lines.append(label)
        for r in group:
            lines.append(
                f"{r['count']:>6}  {r['kind']:<11} {r['slug']:<28} {r['proposed_name']:<22} "
                f"{r['score']:.2f}  {r['title'][:40]}"
            )
        lines.append("")
    (WORK / "intake_review.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"rows={len(out)} add={len(add)} review={len(review)} skip={len(skip)}")


if __name__ == "__main__":
    main()
