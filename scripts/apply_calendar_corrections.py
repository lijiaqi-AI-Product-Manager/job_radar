"""按已审核清单修正现有日历快照；不采集、不改 schema、不刷新观测时间。"""

import argparse
import json
import sqlite3
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def apply_corrections(conn, manifest: dict, *, apply=False) -> dict:
    corrected_on = str(manifest["corrected_on"])
    counts = dict(eligible=0, corrected=0, absent=0, unchanged=0)
    updates = []
    for eid, previous in manifest["withdrawn_deadlines"].items():
        row = conn.execute("SELECT origin, apply_end, as_of, notes FROM entry WHERE id=?", (eid,)).fetchone()
        if row is None:
            counts["absent"] += 1
            continue
        # 不覆盖后续核实、不碰自动条目、不撤回与清单不符的真实日期。
        if row[0] != "manual" or row[1] != str(previous) or str(row[2])[:10] >= corrected_on:
            counts["unchanged"] += 1
            continue
        note = (row[3] or "").replace("网申时间证据：", "公告证据（不证明网申截止）：")
        note += f"；截止日修正（{corrected_on}）：撤回高校公告展示过期日，企业网申截止待核实"
        updates.append((note, eid))
    counts["eligible"] = len(updates)
    if apply:
        with conn:
            conn.executemany("UPDATE entry SET apply_end=NULL, notes=? WHERE id=?", updates)
        counts["corrected"] = len(updates)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "calendar/corrections/2026-11-01-deadlines.yaml")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    # mode=rw 防止输错路径时静默创建空数据库。
    conn = sqlite3.connect(args.db.resolve().as_uri() + "?mode=rw", uri=True)
    try:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("calendar database integrity check failed")
        print(json.dumps(apply_corrections(conn, manifest, apply=args.apply), ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
