"""跑南开 34 个 campus 源的 crawl 冒烟，并统计每源入库岗位数。

用法：python work/crawl_campus_smoke.py [--out DIR]
输出 work/_campus_crawl.txt
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "_campus_crawl.txt"


def main() -> int:
    out_dir = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "work" / "_crawl_campus"
    import yaml

    data = yaml.safe_load((ROOT / "sources" / "campus.yaml").read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["sources"]]
    cmd = [
        sys.executable,
        "-X", "utf8",
        "-m", "jobradar.cli",
        "crawl",
        "--only", ",".join(ids),
        "--out", str(out_dir),
    ]
    print("running", len(ids), "sources ->", out_dir, flush=True)
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (proc.stdout or "")[-1500:] + "\n[stderr]\n" + (proc.stderr or "")[-800:]
    print(tail)

    db = out_dir / "jobs.db"
    lines = [f"exit={proc.returncode}", f"ids={len(ids)}"]
    if db.exists():
        con = sqlite3.connect(db)
        rows = con.execute("select source_id, count(*) from job group by source_id").fetchall()
        con.close()
        c = Counter(dict(rows))
        lines.append(f"total_jobs={sum(c.values())} sources_with_jobs={len(c)}")
        for sid in ids:
            lines.append(f"{sid}\t{c.get(sid, 0)}")
        missing = [s for s in ids if not c.get(s)]
        lines.append("zero=" + ",".join(missing))
    else:
        lines.append("no db")
    OUT.write_text("\n".join(lines) + "\n" + tail, encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
