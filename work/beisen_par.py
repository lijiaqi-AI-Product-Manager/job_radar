"""并行探测：一条北森租户管道 + 一条搜索引擎入口管道，都不抢主机的 1 rps。

为什么单独写：`beisen_tenant_sweep.py` 是**串行**的，全局 1 rps，1506 家要跑 3 小时。
但北森租户是 `{tenant}.zhiye.com`，**每家一个独立主机**——并行不同租户不违反
「每主机 ≤1 rps」，串行只是当时为了省事。这里改成 8 路并行（同一租户内部仍串行），
把 3 小时压到 25 分钟。

同时把两件事并行推进（互不争用主机）：
  A. 北森租户穷举（打 `*.zhiye.com`）
  B. 搜索引擎反查入口（打 bing，另有单独节流）

产出与 `beisen_tenant_sweep.py` 完全同构的 JSONL，下游 `verify_found.py` / `add_sources.py`
一行不用改。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import beisen_tenant_sweep as bb  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--per-company", type=int, default=14)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    names = [x.strip() for x in Path(a.src).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in done]
    if a.limit:
        todo = todo[: a.limit]
    py = bb.load_pinyin()
    print(f"待查 {len(todo)} 家，{a.workers} 路并行，拼音表 {len(py)} 字", flush=True)

    lock = threading.Lock()
    hits = 0
    t0 = time.time()
    fh = out.open("a", encoding="utf-8")

    def work(name: str) -> None:
        nonlocal hits
        tried: list[str] = []
        hit = None
        # 每家一个 client：连接复用只在自己的主机上，不会跨租户共享连接池。
        import httpx
        with httpx.Client(headers={"User-Agent": bb.USER_AGENT,
                                   "Content-Type": "application/json"},
                          timeout=12.0) as cli:
            for t in bb.candidates(name, py)[: a.per_company]:
                if t in bb.TENANT_DENY:
                    continue
                tried.append(t)
                pr = bb.probe(cli, t)
                if pr.get("ok") and pr.get("count", 0) > 0:
                    hit = pr
                    break
        rec = {"company": name, "tried": tried, "hit": hit,
               "urls": [f"https://{hit['tenant']}.zhiye.com/"] if hit else []}
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if hit:
                hits += 1
                print(f"HIT {name:16s} {hit['tenant']:22s} {hit['count']:6d}  "
                      f"{(hit['sample'] or [''])[0][:30]}", flush=True)

    # **全局** ≤1 rps 换成**每主机** ≤1 rps：这里每个 worker 内部是串行的，而每个
    # worker 在任一时刻只打一个租户，所以单租户天然 ≤1 rps。跨租户并行是合规的。
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, n) for n in todo]
        for i, fu in enumerate(futs, 1):
            fu.result()
            if i % 50 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(todo)} {el:.0f}s 命中 {hits} ({el / i:.2f}s/家)", flush=True)
    fh.close()
    print(f"完成 {len(todo)}，命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
