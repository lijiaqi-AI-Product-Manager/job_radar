"""把 work/careers_ats2.jsonl 里已确认招聘页反查出的平台入口逐条探活、定归属。

输入 careers_ats2.jsonl：{company, sector, found:{kind, slug|tenant|host, via, url}}
输出 work/search_verified_clean.jsonl（追加，按 platform+slug 去重）

- 北森/飞书：直接探 slug
- 大易：slug 是 SU… 才行，否则抓 found.url 里的 SU id
- beisen_host：对白标主机打 Jobad 接口取 <title>
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))
from verify_search_hits import SU_RE, beisen_probe, brand, feishu_probe, hotjob_probe  # noqa: E402

SRC = ROOT / "work" / "careers_ats2.jsonl"
OUT = ROOT / "work" / "search_verified_clean.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}
JUNK = {"wecruit", "portal-oss", "www", "app", "campus", "careers", "job", "jobs", "zhiye", "moka", "itcast1"}


def one(cli: httpx.Client, company: str, f: dict) -> dict | None:
    kind = f.get("kind")
    slug = str(f.get("slug") or f.get("tenant") or "").strip()
    url = f.get("url") or ""
    try:
        if kind == "beisen":
            if not slug or slug.lower() in JUNK or "." in slug:
                return None
            r = beisen_probe(cli, slug)
            return {"platform": "beisen", "slug": slug, "host": f"{slug}.zhiye.com", **r}
        if kind == "beisen_host":
            host = str(f.get("host") or "").strip()
            if not host or "." not in host:
                return None
            r = cli.post(f"https://{host}/api/Jobad/GetJobAdPageList",
                         json={"PageIndex": 1, "PageSize": 10, "DisplayFields": ["Category", "LocNames", "PostDate"]},
                         headers={"Referer": f"https://{host}/"}, timeout=20.0)
            d = r.json()
            html = cli.get(f"https://{host}/", timeout=20.0, follow_redirects=True).text
            import re
            m = re.search(r"<title>([^<]*)</title>", html)
            return {"platform": "beisen", "slug": host.split(".")[0], "host": host,
                    "count": int(d.get("Count") or 0), "title": (m.group(1) if m else "").strip()}
        if kind == "feishu_atsx":
            if not slug or slug.lower() in JUNK or "." in slug:
                return None
            r = feishu_probe(cli, slug)
            return {"platform": "feishu_atsx", "slug": slug, "host": f"{slug}.jobs.feishu.cn", **r}
        if kind in ("hotjob", "hotjob_probable"):
            if not slug or slug.lower() in JUNK or "." in slug:
                if url:
                    page = cli.get(url, timeout=25.0, follow_redirects=True).text
                    m = SU_RE.search(page)
                    slug = m.group(0) if m else ""
            if not slug or slug.lower() in JUNK or "." in slug:
                return None
            r = hotjob_probe(cli, slug)
            host = f.get("host") or "wecruit.hotjob.cn"
            return {"platform": "hotjob", "slug": slug, "host": host, **r}
    except Exception as e:  # noqa: BLE001
        return {"platform": "err", "slug": slug, "error": f"{type(e).__name__}: {e}"[:80]}
    return None


def main() -> int:
    rows = [json.loads(ln) for ln in SRC.read_text(encoding="utf-8").splitlines() if ln.strip()]
    cands = [(r["company"], r["found"]) for r in rows
             if r.get("found") and r["found"].get("kind") not in ("moka_blocked", "workday", None)]
    print("待探", len(cands), flush=True)
    kept = []
    with httpx.Client(headers=UA, timeout=20.0, follow_redirects=True) as cli, ThreadPoolExecutor(8) as ex:
        for (company, _f), res in zip(cands, ex.map(lambda c: one(cli, *c), cands), strict=False):
            if not res or res.get("error") or int(res.get("count") or 0) <= 0:
                continue
            if brand(company) and brand(company) in brand(res.get("title") or ""):
                res["company"] = company
                kept.append(res)
                print(f"OK {res['platform']:<11} {str(res['slug'])[:24]:<24} {company[:10]:<10} {res['count']:>4} {str(res.get('title'))[:16]}", flush=True)
            else:
                print(f"REJ {res['platform']:<11} {str(res['slug'])[:24]:<24} {company[:10]:<10} title={str(res.get('title'))[:18]}", flush=True)
    old = []
    if OUT.exists():
        old = [json.loads(ln) for ln in OUT.read_text(encoding="utf-8").splitlines() if ln.strip()]
    seen = {(o.get("platform"), str(o.get("slug"))) for o in old}
    add = [k for k in kept if (k.get("platform"), str(k.get("slug"))) not in seen]
    OUT.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in old + add), encoding="utf-8")
    print(f"完成：探 {len(cands)}，保留 {len(kept)}，新增 {len(add)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
