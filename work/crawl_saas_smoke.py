"""对 yunjiuye 全部源做一次真实抓取冒烟，统计每源岗位数与 JD 情况。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

OUT = ROOT / "work" / "_saas_crawl.txt"


def main() -> int:
    sources = [s for s in load_sources(ROOT / "sources") if s.adapter == "yunjiuye"]
    if "--only-zero" in sys.argv and OUT.exists():
        zero = {
            line.split("\t")[0]
            for line in OUT.read_text(encoding="utf-8").splitlines()
            if line.count("\t") >= 2 and line.split("\t")[1].isdigit() and int(line.split("\t")[1]) <= 0
        }
        sources = [s for s in sources if s.id in zero]
        print(f"only-zero: {len(sources)} sources")
    adapters = load_all()
    rows = []
    with make_client() as client:
        for s in sources:
            cls = adapters.get(s.adapter)
            if cls is None:
                rows.append((s.id, -3, "no adapter"))
                continue
            n = 0
            jd = 0
            err = ""
            try:
                ad = cls(s, client)
                for job in ad.fetch_all():
                    n += 1
                    if job.description:
                        jd += 1
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"[:120]
            rows.append((s.id, n, f"jd={jd} {err}".strip()))
    lines = [f"# {len(rows)} sources, ok={sum(1 for r in rows if r[1] > 0)}",
             *[f"{i}\t{n}\t{note}" for i, n, note in rows]]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[0])
    zero = [r for r in rows if r[1] <= 0]
    print("zero/err:", len(zero))
    for r in zero[:10]:
        print(" ", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
