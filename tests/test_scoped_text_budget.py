"""结构化条件限定到小集合时，不应扫描全库正文。"""

import pytest

from helpers import T, make_job
from jobradar.core.queries import search_jobs
from jobradar.pipeline.ingest import ingest_run, upsert_texts


@pytest.mark.parametrize("filters", [
    {"company": "腾讯"}, {"city": "深圳"}, {"grad_year": 2027},
    {"recruit_type": "campus"}, {"category": "技术"}, {"deadline_before": "2026-11-20"},
])
def test_selective_text_query_has_a_bounded_database_budget(jobs_db, text_db, filters):
    wanted = make_job(1, company="腾讯", cities=["深圳"], grad_year=2027,
                      recruit_type="campus", category="技术", apply_end="2026-11-20", description="Python")
    rest = [make_job(i, company="其他公司", cities=["上海"], grad_year=2026,
                     recruit_type="social", category="产品", apply_end="2026-11-21", description="Python")
            for i in range(2, 5002)]
    ingest_run(jobs_db, "s1", [wanted, *rest], ts=T(1))
    upsert_texts(text_db, [wanted, *rest], ts=T(1))
    callbacks = []
    def progress():
        callbacks.append(True)
        return len(callbacks) > 50
    text_db.set_progress_handler(progress, 100)
    try:
        metadata = {}
        rows = search_jobs(jobs_db, text="Python", text_conn=text_db, meta=metadata, **filters)
    finally:
        text_db.set_progress_handler(None, 0)
    assert [row["id"] for row in rows] == [wanted.id]
    assert metadata["total"] == 1 and not metadata["truncated"]


@pytest.mark.parametrize("count", [10000, 10001])
def test_candidate_strategy_boundary_does_not_truncate_matches(jobs_db, text_db, count):
    jobs = [make_job(i, company="腾讯", description="Python") for i in range(count)]
    ingest_run(jobs_db, "s1", jobs, ts=T(1))
    upsert_texts(text_db, jobs, ts=T(1))
    metadata = {}
    rows = search_jobs(jobs_db, company="腾讯", text="Python", text_conn=text_db, limit=7, meta=metadata)
    assert len(rows) == 7
    assert metadata["total"] == count and metadata["truncated"]


def test_scoped_text_search_keeps_the_callers_uncommitted_changes(jobs_db, text_db):
    job = make_job(1, description="Python")
    ingest_run(jobs_db, "s1", [job], ts=T(1))
    upsert_texts(text_db, [job], ts=T(1))
    text_db.execute("UPDATE job_text SET description='TensorFlow'")
    assert search_jobs(jobs_db, company="腾讯", text="TensorFlow", text_conn=text_db)
    assert text_db.in_transaction
    text_db.rollback()
    assert text_db.execute("SELECT description FROM job_text").fetchone()[0] == "Python"
