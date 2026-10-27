"""把「验证通过的线索」汇总成待收录清单（不直接改 YAML）。

为什么要单独一步：验证结果散在 JSONL 里，而写 YAML 必须查重、必须带证据注释。
中间隔一层清单，既能人工过一遍，也能让 `add_sources.py` 只做机械写入。

收录规则：
  1. `ok` 且 `count > 0`；
  2. 归属有证据：`name_hit`（页面/岗位名里出现公司名）**或** `code_prefix` 非空；
  3. 同一租户只保留一次；与 `sources/` 已有的 id / tenant 不重复。

**别名归一**：搜索结果里同一家公司可能有多种写法（`中国铁建`/`中铁建工`），
必须有一个显式别名表 `work/company_alias.json`，否则同一集团会被记成两家公司。
别名表只放**明确同一实体**的写法，拿不准的不合并——错并比不并更糟。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


def clean_company(n: str) -> str:
    """公司名只允许中文/字母/数字/`·`，长度 2~20。

    脏名字（`华夏基金\\n=` 这种）宁可丢掉——公司名错了会污染「按公司筛」，
    比少收录一家更糟。
    """
    n = re.sub(r"\s+", "", n or "")
    n = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9·]", "", n)
    return n if 2 <= len(n) <= 20 else ""


def alias_map() -> dict[str, str]:
    """{写法: 规范名}。缺文件就当空表。"""
    p = ROOT / "work/company_alias.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def existing() -> tuple[set[str], set[str], set[str]]:
    """返回 (已有 id, 已有 beisen tenant, 已有 hotjob host/tenant)。"""
    ids: set[str] = set()
    beisen: set[str] = set()
    hot: set[str] = set()
    for p in (ROOT / "sources").glob("*.yaml"):
        if p.name == "_example.yaml":
            continue
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        rows = d.get("sources") or ([d] if d.get("id") else [])
        for s in rows:
            if s.get("id"):
                ids.add(s["id"])
            pr = s.get("params") or {}
            if (s.get("adapter") == "beisen" or p.name == "beisen.yaml") and pr.get("tenant"):
                beisen.add(pr["tenant"])
            if s.get("adapter") == "hotjob" and pr.get("tenant"):
                hot.add((pr.get("host", "wecruit.hotjob.cn"), pr["tenant"]))
    return ids, beisen, hot


def dedupe_host_tenant(rows: list[dict], key: str = "tenant") -> tuple[list[dict], list[dict]]:
    """同一租户只留一条（不同搜索词会命中同一个租户）。

    留哪条：公司名更长的不一定对（`jingxinpharm1` 只是同一家的备用门户），
    所以规则是「**先出现、且已核过 title 的优先**」——`name_hit` 为真说明页面里
    真写了这家公司名，比搜索词本身可信。
    """
    keep: dict[tuple[str, str], dict] = {}
    drop: list[dict] = []
    for r in sorted(rows, key=lambda x: (not x.get("name_hit"), x["tenant"])):
        k = (r.get("host", ""), r[key])
        if k not in keep:
            keep[k] = r
        elif len(r["company"]) > len(keep[k]["company"]):
            drop.append(keep[k])
            keep[k] = r
        else:
            drop.append(r)
    return list(keep.values()), drop


def main() -> int:
    inp = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/exp/verified.jsonl")
    outp = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/exp/to_add.json")
    ids, beisen, hot = existing()
    alias = alias_map()

    beisen_rows: list[dict] = []
    hot_rows: list[dict] = []
    skipped: list[dict] = []
    for ln in inp.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        comp = clean_company(r.get("company") or "")
        if not (r.get("ok") and (r.get("count") or 0) > 0):
            continue
        if not comp:
            skipped.append({"why": "公司名不可用", "raw": r.get("company")})
            continue
        comp = alias.get(comp, comp)
        ev = bool(r.get("name_hit")) or bool(r.get("code_prefix"))
        if not ev:
            skipped.append({"why": "无归属证据", "company": comp,
                            "slug": r.get("slug"), "tenant": r.get("tenant")})
            continue
        base = {"company": comp, "count": r["count"], "title": r.get("title", ""),
                "name_hit": bool(r.get("name_hit")),
                "jobs": (r.get("jobs") or [])[:2],
                "city": f"{r.get('with_city', 0)}/{r.get('sample', 0)}",
                "date": f"{r.get('with_date', 0)}/{r.get('sample', 0)}"}
        if r["kind"] == "beisen":
            slug = r["slug"]
            if not SLUG_OK.match(slug) or slug in beisen:
                skipped.append({"why": "重复/非法 slug", "slug": slug, "company": comp})
                continue
            beisen_rows.append({**base, "id": f"beisen-{slug}", "tenant": slug})
        else:
            hot_rows.append({**base, "id": "", "host": r["host"], "tenant": r["tenant"],
                             "prefix": r.get("code_prefix") or []})

    beisen_rows, bdrop = dedupe_host_tenant(beisen_rows, "tenant")
    skipped += [{"why": "同一租户重复", "company": d["company"], "tenant": d["tenant"]}
                for d in bdrop]
    hot_rows, dropped = dedupe_host_tenant([r for r in hot_rows
                                            if (r["host"], r["tenant"]) not in hot])
    skipped += [{"why": "同一租户重复", "company": d["company"], "tenant": d["tenant"]}
                for d in dropped]

    # 同一家公司只留一个门户：`jingxinpharm1` 和 `jingxinpharm` 是同一家（110 岗完全一致），
    # 两个都收会让「公司数」虚高，岗位数一点没多。留岗多的那个。
    # 先按「岗多」排序，首次出现的公司被保留，后面同名的记进 skipped；
    # 然后按这个顺序过滤原列表（不能用 set 判断，否则同名全都会被留下）。
    rank: dict[str, int] = {}
    for i, r in enumerate(sorted(beisen_rows + hot_rows, key=lambda x: -x["count"])):
        if r["company"] in rank:
            skipped.append({"why": "同一公司多个门户", "company": r["company"],
                            "tenant": r["tenant"]})
            continue
        rank[r["company"]] = i
    keep_key = {c: None for c in rank}
    for r in sorted(beisen_rows + hot_rows, key=lambda x: -x["count"]):
        key = (r.get("host", ""), r["tenant"])
        if r["company"] in keep_key and keep_key[r["company"]] is None:
            keep_key[r["company"]] = key
    beisen_rows = [r for r in beisen_rows
                   if keep_key.get(r["company"]) == ("", r["tenant"])]
    hot_rows = [r for r in hot_rows
                if keep_key.get(r["company"]) == (r["host"], r["tenant"])]

    out = {"beisen": beisen_rows, "hotjob": hot_rows, "skipped": skipped}
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"beisen {len(beisen_rows)}，hotjob {len(hot_rows)}，跳过 {len(skipped)}")
    for r in beisen_rows:
        print(f"  B {r['tenant'][:26]:26s} {r['company'][:12]:12s} {r['count']:6d} 城{r['city']} 日{r['date']}")
    for r in hot_rows:
        print(f"  H {r['host'][:24]:24s} {r['company'][:12]:12s} {r['count']:6d} {r['prefix']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
