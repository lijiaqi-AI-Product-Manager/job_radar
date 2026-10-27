"""companies.jsonl 的数据回归：别让它再长出「西门子 / 西门子中国」这种重复行。

只做结构 + 唯一性检查，不联网：这一层要能进 CI。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROWS = [json.loads(line) for line in open(ROOT / "companies.jsonl", encoding="utf-8") if line.strip()]

REQUIRED = {"company", "ats", "careers_url", "roles", "calendar_entries", "verified_at", "evidence"}
SUFFIX = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团控股|集团|控股|股份|公司)$")
PAREN = re.compile(r"[（(][^)）]*[)）]")
KEEP_CN = {"中国黄金", "中国建筑", "中国中铁", "中国铁建", "中国交建", "中国电建",
           "中国能建", "中国中车", "中国船舶", "中国移动", "中国电信", "中国联通",
           "中国石油", "中国石化", "中国海油", "中国人寿", "中国银行"}
AGGREGATORS = ("zhipin.com", "liepin.com", "zhaopin.com", "51job.com", "nowcoder.com", "kanzhun.com")


def norm(name: str) -> str:
    n = PAREN.sub("", (name or "").strip()).replace(" ", "")
    while True:
        m = SUFFIX.search(n)
        if not m or len(n) - len(m.group(0)) < 2:
            break
        n = n[: m.start()]
    if n.startswith("中国") and len(n) > 2 and n not in KEEP_CN:
        n = n[2:]
    if n.endswith("中国") and len(n) > 2:
        n = n[:-2]
    return n


def test_rows_have_required_fields() -> None:
    missing = [r.get("company") for r in ROWS if not REQUIRED <= set(r)]
    assert not missing, f"字段不全：{missing[:5]}"


def test_company_names_unique_after_normalization() -> None:
    seen: dict[str, str] = {}
    dupes = []
    for r in ROWS:
        k = norm(r["company"])
        if k in seen:
            dupes.append((seen[k], r["company"]))
        else:
            seen[k] = r["company"]
    assert not dupes, f"同一公司多行：{dupes[:5]}"


def test_no_aggregator_entry() -> None:
    bad = [r["company"] for r in ROWS if any(a in (r.get("careers_url") or "") for a in AGGREGATORS)]
    assert not bad, f"入口指向聚合站：{bad[:5]}"


def test_version_is_pinned() -> None:
    from jobradar import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__
    assert ROWS, "companies.jsonl 为空"
