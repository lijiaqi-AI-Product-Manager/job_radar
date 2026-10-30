"""把云就业职位匹配结果写成 sources/yunjiuye.yaml。

输入 work/_saas_jobs_match.txt（saas_jobs_match.py 产出，列：目标/登记名列表/最优学校站/条数）
每个目标只挂一条源，host 取命中条数最多的学校站，match 为该站上出现过的公司全名。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATCH = ROOT / "work" / "_saas_jobs_match.txt"
OUT = ROOT / "sources" / "yunjiuye.yaml"

# 目标名 -> 拒收原因（人工复核后填）
REJECT: dict[str, str] = {}


def slugify(name: str, table: dict[str, str]) -> str:
    out = []
    for ch in name:
        if ch.isascii() and (ch.isalnum() or ch in "-_"):
            out.append(ch.lower())
        else:
            out.append(table.get(ch, ""))
    return re.sub(r"[^a-z0-9]+", "", "".join(out)) or "x"


HEADER = """# 「云就业」SaaS 高校就业网源（聚合口径 grade C）。
# 全国 1,000+ 所高校的就业网跑在同一套 SaaS 上，每校一个子域，共用公开 JSON 接口
# `/module/getjobs`（列表）与 `/detail/job?id=`（详情，服务端渲染，含岗位职责）。
# 2026-10-30 首批：枚举 1,015 个子域，逐站拉职位库，按公司全名严格对齐目标池后建源。
# 合规：公开接口、无登录/验证码/签名；只读，默认 1 rps。
# 归属：params.match 是学校站上登记的公司全名，归一后完全相等才入库。
"""

DEFAULTS = {
    "adapter": "yunjiuye",
    "recruit_types": ["campus", "intern"],
    "rate_limit_rps": 1,
    "params": {
        "max_pages": 5,
        "fetch_detail": True,
    },
    "compliance": {
        "checked_on": "2026-10-30",
        "robots": "allowed",
        "terms": "高校就业网公开职位列表与详情页，无需登录；不碰学生简历/投递接口",
        "notes": "聚合渠道 grade C：岗位由学校就业网发布，不等于公司官网直发；1 req/s。",
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-careers", action="store_true", default=True,
                    help="同时合并宣讲会匹配（work/_saas_match.txt）")
    ap.add_argument("--no-careers", dest="with_careers", action="store_false")
    ap.add_argument("--smoke", type=Path, default=ROOT / "work" / "_saas_crawl.txt",
                    help="冒烟结果文件；只保留有产出的源")
    ap.add_argument("--deny-zero", action="store_true",
                    help="把冒烟文件当零产出黑名单（用于只重测零产出源的那一轮）")
    args = ap.parse_args()
    table = json.loads((ROOT / "work" / "pinyin_single.json").read_text(encoding="utf-8"))
    rows = []
    for line in MATCH.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith(("jobs=", "uncovered=", "target\t")):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        target, ents_raw, host, count = parts[0], parts[1], parts[2], parts[3]
        if target in REJECT:
            continue
        try:
            ents = ast.literal_eval(ents_raw)
        except (ValueError, SyntaxError):
            continue
        if not host or not ents:
            continue
        rows.append({"company": target, "host": host, "match": list(ents), "count": int(count or 0)})

    # 职位库匹配（jobs）优先；宣讲会匹配（careers）补上职位库里没对上的目标。
    # 两份文件格式略不同：careers 的第 3 列是「逗号分隔的多个学校站」，取第一个。
    by_company = {r["company"]: r for r in rows}
    careers = ROOT / "work" / "_saas_match.txt"
    if careers.exists() and args.with_careers:
        for line in careers.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith(("items=", "target\t")):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            target, ents_raw, count, hosts = parts[0], parts[1], parts[2], parts[3]
            if target in REJECT or target in by_company:
                continue
            try:
                ents = ast.literal_eval(ents_raw)
            except (ValueError, SyntaxError):
                continue
            host = hosts.split(",")[0].strip()
            if not host or not ents:
                continue
            by_company[target] = {"company": target, "host": host, "match": list(ents), "count": int(count or 0)}
    rows = sorted(by_company.values(), key=lambda r: r["company"])

    # 冒烟抓取 0 岗的源不发布（只挂实测有产出的源）
    if args.smoke and args.smoke.exists():
        ok: set[str] = set()
        bad: set[str] = set()
        for line in args.smoke.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
                (ok if int(parts[1]) > 0 else bad).add(parts[0])
        before = len(rows)
        if args.deny_zero:
            # 冒烟文件是「只重测零产出源」那一轮的结果，当黑名单用
            rows = [r for r in rows if f"yunjiuye-{slugify(r['company'], table)}" not in bad]
        else:
            rows = [r for r in rows if f"yunjiuye-{slugify(r['company'], table)}" in ok]
        print(f"smoke filter: {before} -> {len(rows)} (ok={len(ok)} zero={len(bad)})")

    ids = [f"yunjiuye-{slugify(r['company'], table)}" for r in rows]
    if len(set(ids)) != len(ids):
        seen, dup = set(), []
        for i in ids:
            if i in seen:
                dup.append(i)
            seen.add(i)
        raise SystemExit(f"dup ids: {dup[:5]}")
    if len({r["company"] for r in rows}) != len(rows):
        raise SystemExit("dup companies")

    body = [HEADER, "defaults:\n"]
    for k, v in DEFAULTS.items():
        if k == "params":
            body.append("  params:\n")
            for pk, pv in v.items():
                body.append(f"    {pk}: {json.dumps(pv) if isinstance(pv, bool) else pv}\n")
        elif k == "compliance":
            body.append("  compliance:\n")
            for ck, cv in v.items():
                body.append(f'    {ck}: "{cv}"\n' if isinstance(cv, str) and ck in {"terms", "notes"} else f"    {ck}: {cv}\n")
        else:
            body.append(f"  {k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v}\n")
    body.append("\nsources:\n")
    for r, sid in zip(rows, ids, strict=True):
        body.append(
            f"  - id: {sid}\n"
            f"    company: {r['company']}\n"
            f"    params: {{host: {r['host']}, match: {json.dumps(r['match'], ensure_ascii=False)}}}  # {r['count']} 岗\n"
        )
    OUT.write_text("".join(body), encoding="utf-8")
    print(f"sources={len(rows)} -> {OUT}")
    for t, why in REJECT.items():
        print(f"reject {t}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
