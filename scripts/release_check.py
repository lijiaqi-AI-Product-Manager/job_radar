"""发布自检：把 v1.0 的门槛变成可执行的检查，而不是文档里的一句话。

用法：
    uv run python scripts/release_check.py --home ~/.jobradar --sources sources --targets targets/top_companies.yaml

退出码 0 表示全部达标；1 表示有未达标项（逐条打印当前值与门槛）。
在 CI 里可以 nightly 跑一次，提醒离发布还差多少。
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

# v1.0 门槛（可随实际调整，但要有共识后再改）
GATES = {
    "data_coverage": 150,      # 有岗位数据的目标公司数
    "calendar_coverage": 450,  # 至少一条日历条目的目标公司数
    "campus_city": 0.60,       # 校园岗有城市占比
    "jd_coverage": 0.95,       # 在招岗位有 JD 正文占比
}

FILES = ["README.md", "CHANGELOG.md", "COMPLIANCE.md", "LICENSE"]


def _targets(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def data_coverage(targets: dict, companies: set[str]) -> tuple[int, int]:
    matched = match_targets(targets, companies)
    covered = sum(1 for names in matched.values() if names)
    return covered, len(target_names(targets))


def calendar_coverage(calendar_db: Path | None) -> tuple[int, int, int]:
    """返回 (有日历条目的目标数, 目标总数, blocked 数)。"""
    if not calendar_db or not calendar_db.exists():
        return 0, 0, 0
    con = sqlite3.connect(calendar_db)
    try:
        rows = con.execute("SELECT name, data_companies, COALESCE(blocked_reason,'') FROM target").fetchall()
        covered = 0
        blocked = 0
        for name, data_cos, reason in rows:
            if reason:
                blocked += 1
            if name and (json.loads(data_cos or "[]") or con.execute(
                    "SELECT 1 FROM entry WHERE group_name=? LIMIT 1", (name,)).fetchone()):
                covered += 1
        return covered, len(rows), blocked
    finally:
        con.close()


def campus_city_ratio(jobs_db: Path | None) -> float | None:
    if not jobs_db or not jobs_db.exists():
        return None
    con = sqlite3.connect(jobs_db)
    try:
        n = con.execute("SELECT COUNT(*) FROM job WHERE closed_at IS NULL AND recruit_type='campus'").fetchone()[0]
        if not n:
            return None
        hit = con.execute("""SELECT COUNT(*) FROM job WHERE closed_at IS NULL AND recruit_type='campus'
                             AND cities IS NOT NULL AND cities NOT IN ('', '[]')""").fetchone()[0]
        return hit / n
    finally:
        con.close()


def jd_ratio(home: Path | None) -> float | None:
    if not home:
        return None
    jobs, text = home / "jobs.db", home / "jd_text.db"
    if not jobs.exists() or not text.exists():
        return None
    j, t = sqlite3.connect(jobs), sqlite3.connect(text)
    try:
        n = j.execute("SELECT COUNT(*) FROM job WHERE closed_at IS NULL").fetchone()[0]
        if not n:
            return None
        have = t.execute("""SELECT COUNT(*) FROM job_text
                            WHERE (description IS NOT NULL AND description != '')
                               OR (requirements IS NOT NULL AND requirements != '')""").fetchone()[0]
        return min(have, n) / n
    finally:
        j.close()
        t.close()


def run(home: Path | None, sources: Path, targets_path: Path, calendar_db: Path | None) -> list[dict]:
    t = _targets(targets_path)
    companies = {s.company for s in load_sources(sources)}
    rows = []

    covered, total = data_coverage(t, companies)
    rows.append({"gate": "数据源覆盖", "value": f"{covered}/{total}", "ok": covered >= GATES["data_coverage"],
                 "target": f"≥{GATES['data_coverage']}/{total}"})

    cal_covered, cal_total, blocked = calendar_coverage(calendar_db)
    rows.append({"gate": "日历覆盖", "value": f"{cal_covered}/{cal_total}（blocked {blocked}）",
                 "ok": cal_covered >= GATES["calendar_coverage"],
                 "target": f"≥{GATES['calendar_coverage']}/{cal_total}"})

    city = campus_city_ratio(home / "jobs.db" if home else None)
    rows.append({"gate": "校园岗城市覆盖", "value": "无数据" if city is None else f"{city:.1%}",
                 "ok": city is not None and city >= GATES["campus_city"], "target": f"≥{GATES['campus_city']:.0%}"})

    jd = jd_ratio(home)
    rows.append({"gate": "JD 正文覆盖", "value": "无数据" if jd is None else f"{jd:.1%}",
                 "ok": jd is not None and jd >= GATES["jd_coverage"], "target": f"≥{GATES['jd_coverage']:.0%}"})

    missing = [f for f in FILES if not (ROOT / f).exists()]
    rows.append({"gate": "发布文档齐全", "value": "缺少 " + ",".join(missing) if missing else "齐全",
                 "ok": not missing, "target": "README/CHANGELOG/COMPLIANCE/LICENSE"})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=None, help="数据目录（含 jobs.db/jd_text.db/calendar.db）")
    ap.add_argument("--sources", default=str(ROOT / "sources"))
    ap.add_argument("--targets", default=str(ROOT / "targets" / "top_companies.yaml"))
    ap.add_argument("--calendar-db", default=None)
    args = ap.parse_args()
    home = Path(args.home).expanduser() if args.home else None
    cal = Path(args.calendar_db) if args.calendar_db else (home / "calendar.db" if home else None)
    rows = run(home, Path(args.sources), Path(args.targets), cal)
    width = max(len(r["gate"]) for r in rows)
    failed = 0
    for r in rows:
        mark = "PASS" if r["ok"] else "FAIL"
        failed += 0 if r["ok"] else 1
        print(f"{mark}  {r['gate']:<{width}}  {r['value']:<28} 门槛 {r['target']}")
    print("\n发布自检：", "全部达标" if not failed else f"{failed} 项未达标")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
