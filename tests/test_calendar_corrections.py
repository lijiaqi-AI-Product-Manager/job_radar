import importlib.util
import sqlite3
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("calendar_corrections", ROOT / "scripts/apply_calendar_corrections.py")
corrections = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corrections)


def test_corrections_only_withdraw_old_manual_dates_and_are_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE entry(id TEXT, origin TEXT, apply_end TEXT, as_of TEXT, notes TEXT)")
    conn.executemany("INSERT INTO entry VALUES (?,?,?,?,?)", [
        ("bad", "manual", "2026-11-01", "2026-10-27", "原证据链接"),
        ("new", "manual", "2026-11-01", "2026-11-02", "重新核实"),
        ("other", "manual", "2026-12-09", "2026-10-27", "明确网申截止"),
        ("auto", "auto", "2026-11-01", "2026-10-27", "接口字段"),
    ])
    conn.commit()
    manifest = {"corrected_on": "2026-11-01",
                "withdrawn_deadlines": {eid: "2026-11-01" for eid in ("bad", "new", "other", "auto", "absent")}}
    preview = corrections.apply_corrections(conn, manifest)
    assert preview["eligible"] == 1
    assert conn.execute("SELECT apply_end FROM entry WHERE id='bad'").fetchone()[0] == "2026-11-01"
    applied = corrections.apply_corrections(conn, manifest, apply=True)
    assert applied["corrected"] == 1
    rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM entry")}
    assert rows["bad"]["apply_end"] is None and "原证据链接" in rows["bad"]["notes"]
    assert rows["bad"]["as_of"] == "2026-10-27"  # 修正不是新一轮采集
    assert rows["new"]["apply_end"] == rows["auto"]["apply_end"] == "2026-11-01"
    assert rows["other"]["apply_end"] == "2026-12-09"
    assert corrections.apply_corrections(conn, manifest, apply=True)["corrected"] == 0
    conn.close()


def test_repository_deadline_corrections_preserve_body_supported_dates():
    from jobradar.pipeline.calendar import load_manual

    manifest = yaml.safe_load((ROOT / "calendar/corrections/2026-11-01-deadlines.yaml").read_text(encoding="utf-8"))
    entries = {e.id: e for e in load_manual(ROOT / "calendar/entries")}
    for eid in manifest["withdrawn_deadlines"]:
        assert entries[eid].apply_end is None
    for eid, deadline in manifest["retained_with_body_evidence"].items():
        assert entries[eid].apply_end == deadline
