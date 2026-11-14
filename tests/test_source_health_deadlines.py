"""健康摘要中的在招数量与当前查询使用相同的北京时间截止规则。"""

import pytest

from helpers import make_job
from jobradar.core import queries as q
from jobradar.pipeline.ingest import ingest_run


@pytest.mark.parametrize("clock, expected", [
    ("2026-11-14T15:59:59Z", 2),
    ("2026-11-14T16:00:00Z", 1),
])
def test_health_excludes_expired_records_without_changing_history(jobs_db, monkeypatch, clock, expected):
    jobs = [make_job(1, apply_end="2026-11-13"),
            make_job(2, apply_end="2026-11-14"), make_job(3), make_job(4)]
    ingest_run(jobs_db, "s1", jobs, ts="2026-11-10T00:00:00Z")
    jobs_db.execute("UPDATE job SET closed_at='2026-11-11T00:00:00Z' WHERE id='s1:4'")
    ingest_run(jobs_db, "s1", [], ts="2026-11-14T00:00:00Z", ok=False, error="ReadTimeout")
    before = list(jobs_db.execute("SELECT * FROM job ORDER BY id"))
    events = list(jobs_db.execute("SELECT * FROM job_event ORDER BY id"))
    monkeypatch.setattr(q, "now_ts", lambda: clock)

    rows = q.data_status(jobs_db, now=clock)
    assert rows[0]["last_status"] == "failed"
    assert rows[0]["stale"] is True
    assert rows[0]["open_jobs"] == expected
    assert q.data_status_summary(rows)["counts"]["open_jobs"] == expected
    assert q.source_freshness(rows)["stale_open_jobs"] == expected
    assert q.data_summary(jobs_db)["open_jobs"] == expected
    assert len(q.search_jobs(jobs_db)) == expected
    assert len(q.search_jobs(jobs_db, include_closed=True)) == 4
    assert list(jobs_db.execute("SELECT * FROM job ORDER BY id")) == before
    assert list(jobs_db.execute("SELECT * FROM job_event ORDER BY id")) == events


def test_health_uses_explicit_clock_not_process_clock(jobs_db, monkeypatch):
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-11-14")], ts="2026-11-14T00:00:00Z")
    monkeypatch.setattr(q, "now_ts", lambda: "2026-11-15T00:00:00Z")
    assert q.data_status(jobs_db, now="2026-11-14T00:00:00Z")[0]["open_jobs"] == 1
    assert q.data_status(jobs_db, now="2026-11-15T00:00:00Z")[0]["open_jobs"] == 0
