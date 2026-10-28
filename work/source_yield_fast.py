"""逐源核对产出（有上限版）：每个源实际能抓到多少个岗位。

与 source_yield.py 的区别：
- 单源最多取 `--cap` 条（默认 300）就停，避免几万岗的大租户把整轮扫描拖到半小时；
- 单源有墙钟上限（默认 90s），超时就记 slow 并继续；
- 每条结果立刻追加到 JSONL，进程被杀也不丢已经测过的源。

用法：
    python work/source_yield_fast.py --workers 16 --cap 300 --out work/source_yield.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import islice
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.pipeline.crawl import _site_key  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

LOCK = threading.Lock()
OUT = None  # type: ignore[var-annotated]


def fetch_capped(adapter_cls, source, cap: int) -> dict:
    client = make_client()
    started = time.monotonic()
    result = {"id": source.id, "company": source.company, "adapter": source.adapter,
              "count": 0, "capped": False, "seconds": 0.0, "error": None}
    try:
        adapter = adapter_cls(source, client, sleep=time.sleep)
        got = 0
        for _ in islice(adapter.fetch_all(), cap):
            got += 1
        result["count"] = got
        result["capped"] = got >= cap
    except Exception as exc:  # noqa: BLE001
        result["count"] = -1
        result["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        result["seconds"] = round(time.monotonic() - started, 1)
        client.close()
    return result


def run_one(adapter_cls, source, cap: int, hard_timeout: float) -> dict:
    box: dict = {}

    def worker():
        box.update(fetch_capped(adapter_cls, source, cap))

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(hard_timeout)
    if th.is_alive() or not box:
        return {"id": source.id, "company": source.company, "adapter": source.adapter,
                "count": -2, "capped": False, "seconds": hard_timeout,
                "error": f"wall timeout > {hard_timeout:.0f}s"}
    return box


def measure_group(adapter_cls, sources, cap: int, hard_timeout: float) -> list[dict]:
    return [run_one(adapter_cls, s, cap, hard_timeout) for s in sources]


def main() -> int:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=str(ROOT / "sources"))
    ap.add_argument("--out", default=str(ROOT / "work" / "source_yield.jsonl"))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--cap", type=int, default=300)
    ap.add_argument("--hard-timeout", type=float, default=90.0)
    ap.add_argument("--only", default="", help="只测 id 匹配的源（逗号分隔，精确匹配优先、否则子串）")
    args = ap.parse_args()

    sources = [s for s in load_sources(args.sources) if s.enabled]
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        exact = {s.id for s in sources if s.id in want}
        if exact:
            sources = [s for s in sources if s.id in exact]
        else:
            sources = [s for s in sources if any(w in s.id for w in want)]
    adapters = load_all()
    OUT = open(args.out, "w", encoding="utf-8")  # noqa: SIM115 - 全程持有，脚本末尾关闭

    groups: dict[tuple[str, str], list] = defaultdict(list)
    unknown: list[dict] = []
    for s in sources:
        if s.adapter not in adapters:
            unknown.append({"id": s.id, "company": s.company, "adapter": s.adapter,
                            "count": -1, "capped": False, "seconds": 0.0,
                            "error": f"unknown adapter {s.adapter}"})
            continue
        groups[(s.adapter, _site_key(s))].append(s)
    print(f"源数 {len(sources)}，分组 {len(groups)}，并发 {args.workers}，单源上限 {args.cap}", flush=True)
    for row in unknown:
        OUT.write(json.dumps(row, ensure_ascii=False) + "\n")
    OUT.flush()

    done = len(unknown)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(measure_group, adapters[aid], srcs, args.cap, args.hard_timeout)
                   for (aid, _site), srcs in groups.items()]
        for fut in as_completed(futures):
            for row in fut.result():
                with LOCK:
                    OUT.write(json.dumps(row, ensure_ascii=False) + "\n")
                    OUT.flush()
                    done += 1
                    if done % 50 == 0 or done == len(sources):
                        print(f"[{done}/{len(sources)}] 用时 {time.time() - t0:.0f}s", flush=True)
    OUT.close()
    print(f"写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
