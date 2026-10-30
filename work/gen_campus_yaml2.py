"""把多校就业网匹配结果并入 sources/campus.yaml（在已有南开 34 条基础上追加）。

输入 work/_campus_match_all.txt（campus_harvest2.py 产出，列：目标/登记名列表/条数/学校/样例）
规则：
- 同一目标出现在多所学校时，只取「该目标在该校命中条数最多」的那所学校建源，
  避免一家公司挂 3 个源、同一岗位被重复采两遍。
- 拒收名单在 REJECT 里写原因。

用法：python work/gen_campus_yaml2.py [--dry]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MATCH = ROOT / "work" / "_campus_match_all.txt"
OUT = ROOT / "sources" / "campus.yaml"

# 目标名 -> 拒收原因
REJECT: dict[str, str] = {
    "步步高": "命中「东莞市步步高实验学校」，同名不同业",
}

DEFAULTS = {
    "adapter": "campus",
    "recruit_types": ["campus"],
    "rate_limit_rps": 1,
    "params": {
        "school": "nankai",
        "max_pages": 60,
        "list_cache_ttl": 600,
    },
    "compliance": {
        "checked_on": "2026-10-30",
        "robots": "allowed",
        "terms": "公开招聘信息栏目（企业投递给学校的岗位信息），无需登录；不碰学生简历/投递接口",
        "notes": "聚合渠道 grade C：岗位由学校就业网发布，不等于公司官网直发；1 req/s。",
    },
}

HEADER = """# 高校就业网「招聘信息」源（聚合口径 grade C）。
# 该 CMS（路径 /correcruit/）至少三种皮肤，解析见 src/jobradar/adapters/campus.py。
# 第一批 2026-10-30：南开大学（1,000 条 -> 34 家目标）；
# 第二批 2026-10-30：天津工业大学、河北工业大学、天津科技大学（3,600 条 -> 63 家目标）。
# 合规：公开 HTML、无登录/验证码/签名；只读招聘信息栏目；1 req/s。
# 归属：params.match 是该企业在就业网登记的**公司全名**，必须归一后完全相等才入库，
#       模糊匹配会把「迪卡侬…大悦城分公司」错认成「大悦城」、把「步步高实验学校」认成步步高。
"""


def slugify(name: str, table: dict[str, str]) -> str:
    out = []
    for ch in name:
        if ch.isascii() and (ch.isalnum() or ch in "-_"):
            out.append(ch.lower())
        else:
            out.append(table.get(ch, ""))
    s = re.sub(r"[^a-z0-9]+", "", "".join(out))
    return s or "x"


def load_existing() -> list[dict]:
    if not OUT.exists():
        return []
    data = yaml.safe_load(OUT.read_text(encoding="utf-8"))
    out = []
    for s in data.get("sources") or []:
        out.append(
            {
                "id": s["id"],
                "company": s["company"],
                "school": (s.get("params") or {}).get("school", "nankai"),
                "match": s["params"]["match"] if isinstance(s["params"]["match"], list) else [s["params"]["match"]],
            }
        )
    return out


def parse_match_file() -> list[dict]:
    """-> [{target, school, match:[...], count}]，每目标只留命中最多的一所学校。"""
    best: dict[str, tuple[int, str, list[str]]] = {}
    if not MATCH.exists():
        return []
    for line in MATCH.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("postings=") or line.startswith("targets_matched="):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        target, ents_raw, cnt_raw, schools = parts[0], parts[1], parts[2], parts[3]
        try:
            ents = ast.literal_eval(ents_raw)
            cnt = int(cnt_raw)
        except (ValueError, SyntaxError):
            continue
        for school in [s.strip() for s in schools.split(",") if s.strip()]:
            if target not in best or cnt > best[target][0]:
                best[target] = (cnt, school, list(ents))
    return [
        {"target": t, "count": v[0], "school": v[1], "match": v[2]}
        for t, v in sorted(best.items(), key=lambda kv: (kv[1][1], -kv[1][0], kv[0]))
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    table = json.loads((ROOT / "work" / "pinyin_single.json").read_text(encoding="utf-8"))
    entries = load_existing()
    have = {e["company"] for e in entries}
    added = 0
    skipped = []
    for row in parse_match_file():
        t = row["target"]
        if t in REJECT or t in have:
            if t in REJECT:
                skipped.append(f"{t}: {REJECT[t]}")
            continue
        entries.append(
            {
                "id": f"campus-{row['school']}-{slugify(t, table)}",
                "company": t,
                "school": row["school"],
                "match": row["match"],
            }
        )
        have.add(t)
        added += 1

    ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)):
        dup = [i for i in set(ids) if ids.count(i) > 1]
        raise SystemExit(f"dup ids: {dup}")

    by_school: dict[str, int] = defaultdict(int)
    for e in entries:
        by_school[e["school"]] += 1

    body = [HEADER, "defaults:\n"]
    for k, v in DEFAULTS.items():
        if k == "params":
            body.append("  params:\n")
            for pk, pv in v.items():
                body.append(f"    {pk}: {pv}\n")
        elif k == "compliance":
            body.append("  compliance:\n")
            for ck, cv in v.items():
                body.append(f'    {ck}: "{cv}"\n' if ck in {"terms", "notes"} else f"    {ck}: {cv}\n")
        else:
            body.append(f"  {k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v}\n")
    body.append("\nsources:\n")
    for school in sorted({e["school"] for e in entries}):
        body.append(f"  # {school}\n")
        for e in [x for x in entries if x["school"] == school]:
            body.append(
                f"  - id: {e['id']}\n"
                f"    company: {e['company']}\n"
                f"    params: {{school: {school}, match: {json.dumps(e['match'], ensure_ascii=False)}}}\n"
            )
    text = "".join(body)
    if not args.dry:
        OUT.write_text(text, encoding="utf-8")
    print(f"entries={len(entries)} added={added} by_school={dict(by_school)}")
    for s in skipped:
        print("skip:", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
