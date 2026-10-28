"""对 work/careers_sd_hits.jsonl 里的候选逐条探活 + 用门户 <title> 定归属。

只保留「活着（count>0）且标题能对上公司名」的北森/大易命中，输出
work/careers_verified.jsonl，供 apply_sd.py 入库。
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
from verify_tenants_found import beisen_probe, hotjob_probe  # noqa: E402

SRC = ROOT / "work" / "careers_sd_hits.jsonl"
OUT = ROOT / "work" / "careers_verified.jsonl"
UA = {"User-Agent": "Mozilla/5.0 Chrome/126.0"}


def match(title: str, company: str) -> bool:
    from verify_tenants_found import core  # noqa: E402
    t, c = core(title), core(company)
    return bool(t and c) and (c in t or t in c) and len(c) >= 2


def one(cli: httpx.Client, rec: dict) -> dict | None:
    kind, slug = rec["kind"], rec["slug"]
    try:
        if kind in ("beisen", "beisen_host"):
            r = beisen_probe(cli, slug if kind == "beisen" else rec.get("host") or slug)
        elif kind in ("hotjob", "hotjob_legacy"):
            r = hotjob_probe(cli, slug)
        else:
            return None
    except Exception as e:  # noqa: BLE001
        return {**rec, "err": f"{type(e).__name__}: {e}"[:120]}
    title, count = r.get("title") or "", int(r.get("count") or 0)
    if count <= 0 or not title:
        return None
    if not match(title, rec["company"]):
        return {**rec, "reject": "title-mismatch", "title": title, "count": count}
    return {**rec, "verified": True, "title": title, "count": count}


def main() -> int:
    recs = [json.loads(ln) for ln in SRC.read_text(encoding="utf-8").splitlines() if ln.strip()]
    kept, rejected, failed = [], 0, 0
    with httpx.Client(headers=UA, timeout=20.0, follow_redirects=True) as cli, ThreadPoolExecutor(8) as ex:
        for i, res in enumerate(ex.map(lambda r: one(cli, r), recs), 1):
            if res is None:
                continue
            if res.get("err"):
                failed += 1
            elif res.get("reject"):
                rejected += 1
                print(f"REJ {res['slug'][:24]:<24} {res['company'][:12]:<12} title={res['title'][:24]}", flush=True)
            else:
                kept.append(res)
                print(f"OK  {res['kind']:<11} {res['slug'][:24]:<24} {res['company'][:12]:<12} {res['count']:>5} {res['title'][:20]}", flush=True)
            if i % 50 == 0:
                print(f"--- {i}/{len(recs)} kept={len(kept)} rej={rejected} err={failed}", flush=True)
    OUT.write_text("".join(json.dumps(k, ensure_ascii=False) + "\n" for k in kept), encoding="utf-8")
    print(f"完成 {len(recs)}：保留 {len(kept)}、标题不符 {rejected}、异常 {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
