"""逐源核对产出：每个源实际能抓到多少个岗位。

用法：
    python work/source_yield.py --workers 12 --out work/source_yield.json

只读公开接口，口径与 daily crawl 一致（走适配器 fetch_all）。同一站点（同 host/tenant）
仍然串行，保证对单站点的频率承诺不变。结果用来找「源进了库但一条岗都没有」的情况——
这类源每天都要白跑一轮请求，该删或该记进 blocked.jsonl。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.pipeline.crawl import _fetch, _site_key  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

LOCK = threading.Lock()


def measure_group(adapter_cls, sources: list) -> list[dict]:
    client = make_client()
    rows = []
    try:
        for source in sources:
            started = time.time()
            jobs, err, elapsed = _fetch(source, adapter_cls, client, time.sleep)
            rows.append(
                {
                    "id": source.id,
                    "company": source.company,
                    "adapter": source.adapter,
                    "count": -1 if jobs is None else len(jobs),
                    "seconds": round(elapsed, 1),
                    "error": err,
                    "_wall": round(time.time() - started, 1),
                }
            )
    finally:
        client.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=str(ROOT / "sources"))
    ap.add_argument("--out", default=str(ROOT / "work" / "source_yield.json"))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0, help="只测前 N 个源（调试用）")
    args = ap.parse_args()

    sources = [s for s in load_sources(args.sources) if s.enabled]
    if args.limit:
        sources = sources[: args.limit]
    adapters = load_all()
    groups: dict[tuple[str, str], list] = defaultdict(list)
    rows: list[dict] = []
    for s in sources:
        if s.adapter not in adapters:
            rows.append({"id": s.id, "company": s.company, "adapter": s.adapter,
                         "count": -1, "seconds": 0.0, "error": f"unknown adapter {s.adapter}"})
            continue
        groups[(s.adapter, _site_key(s))].append(s)
    print(f"源数 {len(sources)}，分组 {len(groups)}，并发 {args.workers}", flush=True)

    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(measure_group, adapters[aid], srcs) for (aid, _site), srcs in groups.items()]
        for fut in as_completed(futures):
            for row in fut.result():
                with LOCK:
                    rows.append(row)
                    done += 1
                    if done % 50 == 0 or done == len(sources):
                        live = sum(1 for r in rows if r["count"] > 0)
                        zero = sum(1 for r in rows if r["count"] == 0)
                        bad = sum(1 for r in rows if r["count"] < 0)
                        print(f"[{done}/{len(sources)}] 有岗 {live} / 零岗 {zero} / 异常 {bad}"
                              f" 用时 {time.time() - t0:.0f}s", flush=True)

    rows.sort(key=lambda r: r["count"])
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写入 {args.out}：有岗 {sum(1 for r in rows if r['count'] > 0)} / "
          f"零岗 {sum(1 for r in rows if r['count'] == 0)} / 异常 {sum(1 for r in rows if r['count'] < 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
