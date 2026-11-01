import pytest

from helpers import T, make_job
from jobradar.core import queries as q
from jobradar.local import envelope
from jobradar.pipeline.crawl import _enrich
from jobradar.pipeline.ingest import ingest_run, upsert_texts


@pytest.mark.parametrize("stored, requested", [(["深圳市"], "深圳"), (["深圳"], "深圳市")])
def test_equivalent_city_names_recall_existing_records(jobs_db, stored, requested):
    ingest_run(jobs_db, "s1", [make_job(1, cities=stored)], ts=T(1))
    assert len(q.search_jobs(jobs_db, city=requested)) == 1


def test_city_normalization_does_not_guess_position_codes():
    j = make_job(cities=["TP07138", "合肥市,芜湖市", "北京", "北京市"])
    _enrich(j)
    assert j.cities == ["合肥", "芜湖", "北京"]


def test_successful_empty_detail_does_not_preserve_known_template_pollution(text_db):
    original = make_job(description="职位描述 / 单位简介富文本 */ .job-desc { font-size: 14px; }")
    upsert_texts(text_db, [original], ts=T(1))
    upsert_texts(text_db, [make_job(description=None, requirements=None)], ts=T(2))
    assert text_db.execute("SELECT description FROM job_text").fetchone()[0] is None


def test_temporarily_missing_detail_preserves_valid_historical_body(text_db):
    upsert_texts(text_db, [make_job(description="岗位职责：负责软件架构设计。")], ts=T(1))
    upsert_texts(text_db, [make_job(description=None, requirements=None)], ts=T(2))
    assert text_db.execute("SELECT description FROM job_text").fetchone()[0] == "岗位职责：负责软件架构设计。"


def test_recent_global_snapshot_does_not_hide_stale_returned_source(jobs_db, monkeypatch):
    monkeypatch.setattr(q, "now_ts", lambda: "2026-11-01T12:00:00Z")
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    ingest_run(jobs_db, "fresh", [make_job(2, source_id="fresh", company="新来源")], ts="2026-11-01T11:00:00Z")
    rows = q.search_jobs(jobs_db, company="腾讯")
    assert rows[0]["source_stale"] is True
    assert rows[0]["availability"] == "unconfirmed_stale"
    assert envelope(jobs_db, rows)["stale"] is True


def test_events_and_categories_report_total_and_truncation(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, category="技术"), make_job(2, category="产品")], ts=T(1))
    for query in (q.recent_changes, q.new_jobs_by_category):
        meta = {}
        assert len(query(jobs_db, since=T(1), limit=1, meta=meta)) == 1
        assert meta["total"] == 2 and meta["returned"] == 1 and meta["truncated"]


@pytest.mark.parametrize("kwargs", [{"grad_year": 0}, {"grad_year": -2027}, {"recruit_type": "CAMPUZ"}])
def test_invalid_filter_domains_fail_instead_of_broadening(jobs_db, kwargs):
    with pytest.raises(ValueError):
        q.search_jobs(jobs_db, **kwargs)


def test_status_summary_is_bounded_and_reports_omitted_items():
    rows = [dict(source_id=str(i), last_status="failed", last_run=T(1), last_ok=None,
                 stale=True, open_jobs=1, duration_s=1, age_hours=None, error="failed") for i in range(1000)]
    summary = q.data_status_summary(rows)
    assert len(summary["problems"]) <= 20
    assert summary["omitted_problems"] == 980


def test_extreme_days_is_rejected_with_actionable_error():
    with pytest.raises(ValueError, match="days"):
        q.lookback_since(10**12)


def test_calendar_current_quantity_excludes_expired_jobs(tmp_path, jobs_db):
    from jobradar.pipeline.calendar import build
    from jobradar.store.migrate import connect

    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-10-31")], ts=T(1))
    cal = connect(tmp_path / "calendar.db", "calendar")
    try:
        build(cal, jobs_db, manual=[], sources=[], targets={"sectors": {}}, ts="2026-11-01T00:00:00Z")
        rows = q.calendar_entries(cal)
        assert rows[0]["open_jobs"] == 0
        assert q.search_jobs(jobs_db) == []
    finally:
        cal.close()
