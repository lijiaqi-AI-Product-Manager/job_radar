import json

import pytest

from jobradar import cli
from jobradar.core import queries as q
from jobradar.store.migrate import connect


@pytest.fixture
def calendar_db(tmp_path):
    conn = connect(tmp_path / "calendar.db", "calendar")
    for eid, start, end in (("known", "2026-10-01", "2026-11-10"),
                            ("missing-start", None, "2026-11-09"),
                            ("missing-end", "2026-10-01", None),
                            ("missing-both", None, None),
                            ("ended", "2026-10-01", "2026-10-31")):
        conn.execute("INSERT INTO entry(id,origin,group_name,company,project_type,apply_start,apply_end,"
                     "source_type,source_name,as_of,jd_status) VALUES (?, 'manual','示例公司','示例公司',"
                     "'秋招正式批',?,?,'official_site','公开招聘页','2026-10-30','none')", (eid, start, end))
    conn.commit()
    yield conn
    conn.close()


@pytest.mark.parametrize("limit", [1, 10])
def test_open_on_summary_distinguishes_candidates_from_known_windows(calendar_db, limit):
    metadata = {}
    rows = q.calendar_entries(calendar_db, open_on="2026-11-01", limit=limit, meta=metadata)
    assert metadata["total"] == 4
    counts = metadata["window_counts"]
    assert counts["scope"] == "returned"
    assert counts["open"] + counts["unknown"] == len(rows)
    if limit == 1:
        assert counts["unknown"] == 1 and metadata["truncated"]
    else:
        assert counts["open"] == 1 and counts["unknown"] == 3
    assert any("候选" in hint and "可投" in hint for hint in metadata["hints"])


def test_confirmed_window_filter_keeps_only_explicit_batch_dates(calendar_db):
    metadata = {}
    rows = q.calendar_entries(calendar_db, open_on="2026-11-01", confirmed_open_only=True, meta=metadata)
    assert [r["id"] for r in rows] == ["known"]
    assert metadata["total"] == 1 and metadata["window_counts"]["unknown"] == 0
    assert calendar_db.execute("SELECT apply_start FROM entry WHERE id='missing-start'").fetchone()[0] is None


def test_confirmed_window_filter_requires_an_explicit_day(calendar_db):
    with pytest.raises(ValueError, match="open_on"):
        q.calendar_entries(calendar_db, confirmed_open_only=True)


def test_calendar_preserves_the_recorded_cec_route_and_returns_a_working_listing(calendar_db):
    old = "https://campus.cec.com.cn/position/835504585052092"
    calendar_db.execute("UPDATE entry SET apply_url=? WHERE id='known'", (old,))
    row = next(r for r in q.calendar_entries(calendar_db) if r["id"] == "known")
    assert row["recorded_apply_url"] == old
    assert row["apply_url"] == "https://campus.cec.com.cn/position?positionType=0"
    assert row["apply_url_scope"] == "project_listing"
    assert calendar_db.execute("SELECT apply_url FROM entry WHERE id='known'").fetchone()[0] == old


def test_cli_calendar_shows_candidate_warning_and_supports_strict_windows(calendar_db, monkeypatch, capsys):
    path = calendar_db.execute("PRAGMA database_list").fetchone()[2]
    from pathlib import Path

    monkeypatch.setenv("JOBRADAR_HOME", str(Path(path).parent))
    cli.main(["calendar", "--open-on", "2026-11-01", "--table"])
    assert "候选" in capsys.readouterr().out
    cli.main(["calendar", "--open-on", "2026-11-01", "--confirmed-open-only"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1 and payload["results"][0]["id"] == "known"
