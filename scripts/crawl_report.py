"""汇总一次 crawl 的结果：各源状态、岗位分布、字段覆盖率。用于 crawl-check 工作流的日志。"""

import json
import sqlite3
import sys
from pathlib import Path


def main(summary_path: str, data_dir: str) -> int:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    bad = {k: v for k, v in summary.items() if v["status"] != "ok"}
    print(f"sources: {len(summary)}  ok: {len(summary) - len(bad)}  not ok: {len(bad)}")
    for sid, v in sorted(bad.items()):
        print(f"  NOT OK {sid}: {v['status']} {v['reason']}")

    db = sqlite3.connect(Path(data_dir) / "jobs.db")
    q = lambda sql: db.execute(sql).fetchall()  # noqa: E731
    total = q("SELECT COUNT(*) FROM job")[0][0]
    print(f"\njobs: {total}  companies: {q('SELECT COUNT(*) FROM company')[0][0]}")
    print("by recruit_type:", dict(q("SELECT recruit_type, COUNT(*) FROM job GROUP BY 1")))
    print("by grad_year:", dict(q("SELECT grad_year, COUNT(*) FROM job GROUP BY 1 ORDER BY 2 DESC LIMIT 6")))
    print("by batch:", dict(q("SELECT batch, COUNT(*) FROM job GROUP BY 1 ORDER BY 2 DESC")))
    if total:
        for col in ("grad_year", "batch", "degree_min", "department"):
            n = q(f"SELECT COUNT(*) FROM job WHERE {col} IS NOT NULL")[0][0]
            print(f"coverage {col}: {n / total:.0%}")
        n = q("SELECT COUNT(*) FROM job WHERE cities != '[]'")[0][0]
        print(f"coverage cities: {n / total:.0%}")
    text = sqlite3.connect(Path(data_dir) / "jd_text.db")
    print("job_text rows:", text.execute("SELECT COUNT(*) FROM job_text").fetchone()[0])
    print("\ntop companies:")
    for name, n in q("SELECT c.name, COUNT(*) FROM job j JOIN company c ON c.id=j.company_id GROUP BY 1 ORDER BY 2 DESC LIMIT 15"):
        print(f"  {n:6d}  {name}")
    print("\nsample campus 2027 titles:")
    for (t,) in q("SELECT title FROM job WHERE recruit_type='campus' AND grad_year=2027 ORDER BY RANDOM() LIMIT 15"):
        print("  ", t)
    print("\ncampus titles without grad_year (sample):")
    for (t,) in q("SELECT title FROM job WHERE recruit_type='campus' AND grad_year IS NULL ORDER BY RANDOM() LIMIT 15"):
        print("  ", t)
    for f in ("jobs.db", "jd_text.db"):
        print(f"{f}: {(Path(data_dir) / f).stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
