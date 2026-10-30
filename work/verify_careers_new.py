"""验证 careers 反查出的 38 个新候选：探活 + 归属核对。

只信两件东西：接口真的返回岗位（Count>0），以及门户标题里出现这家公司。
标题对不上的（建发房产→chinacdc 中国疾控、极氪→jtexpress 极兔、沐曦→moonton 沐瞳）
一律判 `mismatch`，宁可漏收，不可错收。
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
BAD = {"portal-oss", "www", "m", "api", "campus", "static"}
# 归属错配的已知地雷：slug 上的公司名和标题明显无关
CORE = re.compile(r"(?:股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司|"
                  r"（中国）|\(中国\))$")


def core(s: str) -> str:
    prev, cur = None, s.strip()
    while cur != prev:
        prev, cur = cur, CORE.sub("", cur).strip()
    return cur


def beisen_probe(slug: str) -> dict:
    url = f"https://{slug}.zhiye.com/api/Jobad/GetJobAdPageList"
    body = {"PageIndex": 1, "PageSize": 5, "DisplayFields": ["Category", "LocNames", "PostDate"], "Category": [], "KeyWords": ""}
    with httpx.Client(timeout=20, headers=UA, follow_redirects=True) as c:
        r = c.post(url, json=body)
        if r.status_code != 200:
            return {"state": "dead", "code": r.status_code}
        try:
            data = r.json()
        except Exception:  # noqa: BLE001
            return {"state": "dead", "code": "notjson"}
        count = ((data.get("Data") or {}).get("Count")) or 0
        page = c.get(f"https://{slug}.zhiye.com/")
        m = re.search(r"<title>(.*?)</title>", page.text, re.S)
        return {"state": "alive" if count else "empty", "count": int(count or 0),
                "title": (m.group(1).strip() if m else "")[:80]}


def hotjob_probe(slug: str) -> dict:
    url = f"https://{slug}.hotjob.cn/"
    with httpx.Client(timeout=20, headers=UA, follow_redirects=True) as c:
        r = c.get(url)
        if r.status_code != 200:
            return {"state": "dead", "code": r.status_code}
        m = re.search(r"<title>(.*?)</title>", r.text, re.S)
        t = re.findall(r"(SU[0-9a-f]{20,})", r.text)
        return {"state": "alive" if t else "no_tenant", "tenant": (t[0] if t else ""),
                "title": (m.group(1).strip() if m else "")[:80]}


def feishu_probe(slug: str) -> dict:
    url = f"https://{slug}.jobs.feishu.cn/api/v1/csrf/token"
    with httpx.Client(timeout=20, headers={**UA, "Accept": "application/json"}) as c:
        r = c.post(url, json={"portal_entrance": 1})
        ok = r.status_code == 200 and "token" in r.text
        return {"state": "alive" if ok else "dead", "code": r.status_code}


def main() -> None:
    rows = {}
    for line in (ROOT / "work/careers_ats.jsonl").open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            rows[d["company"]] = d
    targets = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8"))
    srcs = load_sources(ROOT / "sources")
    matched = match_targets(targets, {s.company for s in srcs})
    params = {(s.adapter, json.dumps(s.params, sort_keys=True)) for s in srcs}
    uncovered = {n for n, _ in target_names(targets) if not matched.get(n)}

    jobs: list[tuple[str, str, str]] = []
    for c, d in rows.items():
        f = d.get("found") or {}
        if c not in uncovered or f.get("kind") not in {"beisen", "hotjob", "feishu_atsx"}:
            continue
        slug = (f.get("slug") or "").lower()
        if not slug or slug in BAD:
            continue
        kind = f["kind"]
        key = ""
        if kind == "beisen":
            key = json.dumps({"tenant": slug}, sort_keys=True)
        elif kind == "feishu_atsx":
            key = json.dumps({"tenant": slug}, sort_keys=True)
        if key and (kind, key) in params:
            continue
        jobs.append((c, kind, slug))

    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {}
        for c, kind, slug in jobs:
            fn = {"beisen": beisen_probe, "hotjob": hotjob_probe, "feishu_atsx": feishu_probe}[kind]
            futs[ex.submit(fn, slug)] = (c, kind, slug)
        for fu in futs:
            c, kind, slug = futs[fu]
            try:
                r = fu.result()
            except Exception as e:  # noqa: BLE001
                r = {"state": "error", "err": type(e).__name__}
            r.update({"company": c, "kind": kind, "slug": slug})
            results.append(r)

    # 归属核对：标题里的核心名要能对上公司名核心（或互为子串）
    lines = []
    for r in sorted(results, key=lambda x: (x["state"], x["company"])):
        title = r.get("title") or ""
        tc, cc = core(title), core(r["company"])
        match = ""
        if title:
            match = "ok" if (cc and (cc in title or (tc and (tc in r["company"] or cc[:2] in title)))) else "mismatch"
        r["name_match"] = match
        lines.append(f"{r['state']:9} {match:8} {r['company']:<14} {r['kind']:<11} {r['slug']:<16} "
                     f"count={r.get('count')} title={title}")
    (ROOT / "work" / "_careers_new_verified.txt").write_text("\n".join(lines), encoding="utf-8")
    json.dump(results, (ROOT / "work" / "_careers_new_verified.json").open("w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
