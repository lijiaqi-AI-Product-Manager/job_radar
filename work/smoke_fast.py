"""快速冒烟：并发跑一遍 yunjiuye 源，只翻 2 页、兜底 2 页，判断每源是否有产出。

之前逐源串行 + 每源最多 15 页，154 个源要跑一小时以上；这里把页数压到 2 页、
8 并发，几分钟出结果，足以区分「有岗」和「0 岗」。
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

OUT = ROOT / "work" / "_saas_fast.txt"
ITEMS = json.loads((ROOT / "work" / "saas_jobs.jsonl").read_text(encoding="utf-8").splitlines()[0]) if False else None


def probe(source, cls, client) -> tuple[str, int, int]:
    params = dict(source.params)
    params["max_pages"] = 2
    params["fallback_pages"] = 2
    src = source.model_copy(update={"params": params})
    n = jd = 0
    try:
        for job in cls(src, client).fetch_all():
            n += 1
            if job.description:
                jd += 1
            if n >= 50:
                break
    except Exception:  # noqa: BLE001
        return source.id, -1, 0
    return source.id, n, jd


def main() -> int:
    sources = [s for s in load_sources(ROOT / "sources") if s.adapter == "yunjiuye"]
    adapters = load_all()
    cls = adapters["yunjiuye"]
    print(f"sources={len(sources)}", flush=True)
    rows: list[tuple[str, int, int]] = []
    with make_client() as client, ThreadPoolExecutor(max_workers=8) as pool:
        for row in pool.map(lambda s: probe(s, cls, client), sources):
            rows.append(row)
    rows.sort()
    OUT.write_text(
        f"# {len(rows)} sources, ok={sum(1 for _, n, _ in rows if n > 0)}\n"
        + "\n".join(f"{sid}\t{n}\tjd={jd}" for sid, n, jd in rows)
        + "\n",
        encoding="utf-8",
    )
    ok = [r for r in rows if r[1] > 0]
    print(f"ok={len(ok)} zero={len(rows) - len(ok)} jobs={sum(n for _, n, _ in ok)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
