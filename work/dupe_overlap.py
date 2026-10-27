"""同一公司挂了多条源时，量一下两个门户到底重不重复（只比北森系，带单源超时）。

对每组同公司源各抓最多 250 条，用「标题 + 首个城市」做键算 Jaccard。
重合度 ≥0.8 基本可以确定是同一套岗位的双门户，留一条即可。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.pipeline.crawl import _fetch  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

CAP = 250
SLEEP = 1.05
TIMEOUT = 45
ONLY_ADAPTERS = {"beisen", "beisen_legacy"}


def keyset(jobs) -> set[str]:
    out = set()
    for j in jobs[:CAP]:
        city = (j.cities[0] if j.cities else "").strip()
        out.add(f"{j.title.strip().lower()}|{city}")
    return out


def fetch_with_timeout(source, cls, timeout: float = TIMEOUT):
    result: dict = {}

    def run() -> None:
        client = make_client()
        try:
            result["val"] = _fetch(source, cls, client, time.sleep)
        except Exception as exc:  # noqa: BLE001
            result["err"] = f"{type(exc).__name__}: {exc}"
        finally:
            client.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return None, "wall timeout"
    jobs, err, _ = result.get("val") or (None, result.get("err"), None)
    return jobs, err


def main() -> int:
    sources = load_sources(ROOT / "sources")
    by_company: dict[str, list] = defaultdict(list)
    for s in sources:
        if s.adapter in ONLY_ADAPTERS:
            by_company[s.company].append(s)
    groups = {c: ss for c, ss in by_company.items() if len(ss) > 1}

    adapters = load_all()
    rows = []
    for company, ss in sorted(groups.items()):
        sets: dict[str, set[str]] = {}
        counts: dict[str, int] = {}
        for s in ss:
            jobs, err = fetch_with_timeout(s, adapters[s.adapter])
            if err or not jobs:
                counts[s.id] = -1
                print(f"  ! {s.id} 抓取失败：{err}", flush=True)
                continue
            sets[s.id] = keyset(jobs)
            counts[s.id] = len(jobs)
        ids = list(sets)
        for i in range(len(ids)):
            for k in range(i + 1, len(ids)):
                a, b = ids[i], ids[k]
                inter = len(sets[a] & sets[b])
                union = len(sets[a] | sets[b]) or 1
                rows.append(
                    {
                        "company": company,
                        "a": a,
                        "b": b,
                        "count_a": counts[a],
                        "count_b": counts[b],
                        "overlap": round(inter / union, 3),
                    }
                )
        print(f"{company}: " + ", ".join(f"{i}={counts.get(i)}" for i in ids), flush=True)

    out = ROOT / "work" / "dupe_overlap.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print("\n重合度（>=0.8 视为同一套岗位）")
    for r in sorted(rows, key=lambda r: -r["overlap"]):
        print(f"  {r['overlap']:.2f}  {r['company']}: {r['a']}({r['count_a']}) vs {r['b']}({r['count_b']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
