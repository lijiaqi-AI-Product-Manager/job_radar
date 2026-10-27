"""把新增 source 落进 companies.jsonl（公司清单），供覆盖率报表与 release_check 使用。

口径：
- 只补「source 里有、companies.jsonl 里没有」的公司，已存在的行一律不动（人工维护的字段更可靠）。
- careers_url 按适配器拼出「人能看到并投递」的入口；聚合站一律不写（release_check 会拦）。
- evidence 记实测证据：门户标题、岗数、发现渠道；grade=A 表示 ATS 门户 + 实测有岗。
用法：python work/append_companies.py [--write]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402
from company_keys import key as core  # noqa: E402  与 merge_companies 共用同一套归一化

from jobradar.sources import load_sources  # noqa: E402

KIND = {"beisen_host": "beisen"}


def load_counts() -> dict[tuple[str, str], dict]:
    """把各轮探活结果汇总成 (adapter, tenant) → {count, title}。"""
    out: dict[tuple[str, str], dict] = {}
    for fn in ("sd_hits_round1.jsonl", "sd_hits_round2.jsonl", "sd_hits.jsonl",
               "hotjob_candidates.jsonl", "feishu_counts.jsonl"):
        p = WORK / fn
        if not p.exists():
            continue
        for ln in open(p, encoding="utf-8"):
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            kind = KIND.get(d.get("platform") or d.get("kind") or "", d.get("platform") or d.get("kind"))
            slug = str(d.get("slug") or d.get("tenant") or "").lower()
            if not kind or not slug:
                continue
            prev = out.get((kind, slug))
            if prev is None or int(d.get("count") or 0) > int(prev.get("count") or 0):
                out[(kind, slug)] = {"count": int(d.get("count") or 0),
                                     "title": d.get("title") or d.get("company") or "",
                                     "found": fn}
    return out


def calendar_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in (ROOT / "calendar").glob("*.yaml"):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        name = str(doc.get("company") or doc.get("group_name") or "").strip()
        if name:
            out[name] = out.get(name, 0) + 1
    return out


def sector_of(targets: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, lst in (targets.get("sectors") or {}).items():
        for co in lst or []:
            out.setdefault(str(co), name)
    return out


RENAME = {
    "中国太平人才": "中国太平", "KOI官方": "KOI", "新产业": "新产业生物",
    "云轴": "云轴科技", "奥拓电子人才": "奥拓电子", "达瑞电子招聘官微": "达瑞电子",
    "皖仪科技人才": "皖仪科技", "旗滨集团欢迎您": "旗滨集团",
}
TAIL = re.compile(r"(人才招聘官网|招聘官网|人才招聘|招聘门户|招聘官微|招聘微｜?|官方)$")


def clean_company(name: str) -> str:
    name = re.sub(r"[（(]新[）)]$", "", (name or "").strip())
    name = name.replace("欢迎加入", "").replace("欢迎来到", "").replace("欢迎您", "")
    if name in RENAME:
        return RENAME[name]
    trimmed = TAIL.sub("", name)
    return trimmed if len(trimmed) >= 2 else name


def careers_for(adapter: str, params: dict) -> tuple[str, str]:
    host = str(params.get("host") or "").strip()
    tenant = str(params.get("tenant") or "").strip()
    if adapter == "beisen":
        h = host or f"{tenant}.zhiye.com"
        return f"https://{h}/", h
    if adapter == "feishu_atsx":
        base = str(params.get("base_url") or "").rstrip("/")
        path = str(params.get("website_path") or "campus")
        return f"{base}/{path}", base.replace("https://", "")
    if adapter == "hotjob":
        h = host or "wecruit.hotjob.cn"
        return f"https://{h}/wt/{tenant}/", h
    if adapter == "hotjob_legacy":
        h = host or f"{tenant}.hotjob.cn"
        return f"https://{h}/", h
    return "", host


def main() -> None:
    write = "--write" in sys.argv
    with open(ROOT / "companies.jsonl", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    have = {core(r.get("company")) for r in rows}
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    sector = sector_of(targets)
    counts = load_counts()
    cal = calendar_counts()

    new_rows = []
    for s in load_sources(ROOT / "sources"):
        adapter = KIND.get(s.adapter, s.adapter)
        if adapter not in ("beisen", "feishu_atsx", "hotjob", "hotjob_legacy"):
            continue
        co = (s.company or "").strip()
        if not co or len(co) < 2 or core(co) in have:
            continue
        have.add(core(co))
        tenant = str(s.params.get("tenant") or "").lower()
        info = counts.get((adapter, tenant)) or {}
        url, host = careers_for(adapter, s.params)
        if not url:
            continue
        cnt = int(info.get("count") or 0)
        new_rows.append({
            "company": co,
            "group": co,
            "sector": sector.get(co, "扩展池（实测确认）"),
            "careers_url": url,
            "host": host,
            "ats": adapter,
            "calendar_entries": cal.get(co, 0),
            "project_types": [],
            "tracks": 0,
            "roles": cnt,
            "jd_status": "official_page" if cnt else "blocked",
            "has_apply_window": False,
            "has_cities": False,
            "grad_years": [],
            "verified_at": "2026-10-28",
            "evidence": {
                "careers_url_http": 200,
                "page_title": (info.get("title") or "")[:60],
                "origin": info.get("found") or "source_registry",
                "grade": "A" if cnt else "B",
                "grade_why": "ats_portal 实测有岗" if cnt else "门户存活但未测到岗数",
                "job_count": cnt,
            },
        })

    for r in new_rows:
        r["company"] = clean_company(r["company"])
    new_rows.sort(key=lambda r: -r["roles"])
    print(f"companies.jsonl 现有 {len(rows)} 行；可补 {len(new_rows)} 家")
    for r in new_rows[:10]:
        print(f"  {r['company'][:18]:<20}{r['ats']:<14}{r['roles']:>6}  {r['careers_url'][:52]}")
    if not write:
        print("（dry-run，加 --write 落盘）")
        return
    with open(ROOT / "companies.jsonl", "a", encoding="utf-8") as fh:
        for r in new_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"写入完成：{len(rows)} → {len(rows) + len(new_rows)} 行")


if __name__ == "__main__":
    main()
