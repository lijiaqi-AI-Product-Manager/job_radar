"""companies.jsonl 去重：同一家公司被写成「西门子 / 西门子中国」这种两行。

判定只认两条证据，不靠拼音猜：
  1. 两行指向同一个 source 端点（同 adapter + 同 host + 同 tenant + 同 base_url/website_path）；
  2. 名字归一化后相同（`work/company_keys.py`：去括号、去集团/股份/有限公司等后缀、去前后「中国」）。
第二条会把「中国黄金 / 中国黄金集团」这类真正同一家合成一行，所以先用 --dry-run
把每一组打出来人工过一遍，确认无「华润 vs 华润万家」这种误并再 --write。

用法：python work/merge_companies.py [--write]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from company_keys import key, score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.sources import load_sources  # noqa: E402


def source_endpoint(s) -> tuple:
    """同一门户 = 同 adapter + 同 host + 同 tenant + 同 base_url/website_path。

    tenant 必须进来：大易的几百个源都挂在 wecruit.hotjob.cn 上，只有 tenant 能区分。
    """
    p = s.params or {}
    return (s.adapter,
            str(p.get("host") or "").lower(),
            str(p.get("tenant") or "").lower(),
            str(p.get("base_url") or "").lower(),
            str(p.get("website_path") or "").lower())


def main() -> None:
    write = "--write" in sys.argv
    rows = [json.loads(line) for line in open(ROOT / "companies.jsonl", encoding="utf-8") if line.strip()]
    endpoints: dict[str, tuple] = {}
    for s in load_sources(ROOT / "sources"):
        endpoints.setdefault(s.company, source_endpoint(s))

    parent = list(range(len(rows)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_key: dict[str, int] = {}
    by_ep: dict[tuple, int] = {}
    for i, r in enumerate(rows):
        k = key(r["company"])
        if k in by_key:
            union(by_key[k], i)
        else:
            by_key[k] = i
        ep = endpoints.get(r["company"])
        if ep and any(ep[1:]):
            if ep in by_ep:
                union(by_ep[ep], i)
            else:
                by_ep[ep] = i

    groups: dict[int, list[dict]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(find(i), []).append(r)

    dupes = [g for g in groups.values() if len(g) > 1]
    print(f"companies.jsonl {len(rows)} 行，重复组 {len(dupes)} 个，多出 {sum(len(g) - 1 for g in dupes)} 行")
    for g in sorted(dupes, key=lambda g: -len(g)):
        print("---")
        for r in g:
            print(f"  {r['company']:<24} {r.get('ats', ''):<14} roles={r.get('roles', 0):<7} "
                  f"{r.get('careers_url', '')[:56]}")

    if not write:
        print("（dry-run，确认后加 --write）")
        return

    merged = []
    for g in groups.values():
        if len(g) == 1:
            merged.append(g[0])
            continue
        g = sorted(g, key=score, reverse=True)
        keep = dict(g[0])
        for r in g[1:]:
            keep["calendar_entries"] = max(keep.get("calendar_entries") or 0, r.get("calendar_entries") or 0)
            keep["roles"] = max(keep.get("roles") or 0, r.get("roles") or 0)
            keep["tracks"] = max(keep.get("tracks") or 0, r.get("tracks") or 0)
            keep["project_types"] = sorted(set(keep.get("project_types") or []) | set(r.get("project_types") or []))
            keep["grad_years"] = sorted(set(keep.get("grad_years") or []) | set(r.get("grad_years") or []))
            keep["has_apply_window"] = bool(keep.get("has_apply_window")) or bool(r.get("has_apply_window"))
            keep["has_cities"] = bool(keep.get("has_cities")) or bool(r.get("has_cities"))
            if not keep.get("careers_url") and r.get("careers_url"):
                keep["careers_url"], keep["host"], keep["ats"] = r["careers_url"], r.get("host"), r.get("ats")
            why = (keep.get("evidence") or {}).get("grade_why") or ""
            note = f"同公司别名合并：{r['company']}"
            keep["evidence"] = {**(keep.get("evidence") or {}),
                                "grade_why": f"{why}；{note}" if why else note}
        merged.append(keep)

    with open(ROOT / "companies.jsonl", "w", encoding="utf-8") as fh:
        for r in merged:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"写入完成：{len(rows)} → {len(merged)} 行")


if __name__ == "__main__":
    main()
