"""云就业目标定向搜索：对每个未覆盖目标，在若干学校站上用关键词接口查一遍。

比「逐站翻列表」覆盖更全：列表翻页上限约 500 条/站，而 `k=<公司名>` 是库内检索，
只要这所学校站收过该公司的岗位就能命中。

用法：python work/saas_target_search.py --hosts 24 --targets 0
产物：work/saas_hits.jsonl（每行 {company, host, n, sample}）
每个 host 由一个线程串行扫全部目标，1 rps，避免把单个学校站打爆。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
}
OUT = ROOT / "work" / "saas_hits.jsonl"


def pick_hosts(n: int) -> list[str]:
    from collections import Counter

    rows = [json.loads(x) for x in (ROOT / "work" / "saas_jobs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return [h for h, _ in Counter(r["school_host"] for r in rows).most_common(n)]


def uncovered_targets() -> list[str]:
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    covered = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, covered)
    return [n for n, _ in target_names(targets) if not matched.get(n)]


def scan(host: str, targets: list[str], out_path: Path, lock) -> int:
    hits = 0
    with httpx.Client(timeout=25.0, headers=H, follow_redirects=True, verify=False) as c, \
            out_path.open("a", encoding="utf-8") as fh:
        for t in targets:
            try:
                r = c.get(f"https://{host}/module/getjobs", params={"start": 1, "count": 100, "k": t})
                d = r.json()
            except Exception:  # noqa: BLE001
                time.sleep(1.5)
                continue
            items = (d.get("data") or []) if isinstance(d, dict) and int(d.get("code") or 0) == 1 else []
            comps = sorted({it.get("company_name") for it in items if it.get("company_name")})
            if comps:
                with lock:
                    fh.write(json.dumps({"company": t, "host": host, "n": len(items), "names": comps[:8]}, ensure_ascii=False) + "\n")
                    fh.flush()
                hits += 1
            time.sleep(1.0)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", type=int, default=24)
    ap.add_argument("--targets", type=int, default=0, help="0 = 全部未覆盖目标")
    ap.add_argument("--out", default="work/saas_hits.jsonl")
    args = ap.parse_args()

    import threading

    hosts = pick_hosts(args.hosts)
    targets = uncovered_targets()
    if args.targets:
        targets = targets[: args.targets]
    print(f"hosts={len(hosts)} targets={len(targets)}", flush=True)
    out_path = ROOT / args.out
    if out_path.exists():
        out_path.unlink()
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=len(hosts)) as pool:
        futures = [pool.submit(scan, h, targets, out_path, lock) for h in hosts]
        for i, f in enumerate(futures, 1):
            n = f.result()
            print(f"host {i}/{len(hosts)} hits={n}", flush=True)
    total = sum(1 for _ in out_path.read_text(encoding="utf-8").splitlines())
    print("rows", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
