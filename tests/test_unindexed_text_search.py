import hashlib

import pytest

from helpers import T, make_job
from jobradar.core.queries import search_jobs
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import connect


@pytest.mark.parametrize(
    "term,expected",
    [
        ("PyTorch CUDA", ["s1:1", "s1:2"]),
        ("PyTorch", ["s1:1", "s1:2", "s1:3"]),
        ("%", ["s1:4"]),
        ("不可能出现的文本", []),
    ],
)
def test_first_file_search_returns_exact_results_without_building_indexes(
    tmp_path, monkeypatch, term, expected
):
    monkeypatch.delenv("JOBRADAR_BUILD_SEARCH_INDEX", raising=False)
    jobs = connect(tmp_path / "jobs.db", "jobs", defer_search_index=True)
    text = connect(tmp_path / "jd_text.db", "text", defer_search_index=True)
    rows = [
        make_job(1, title="PyTorch 开发", description="CUDA"),
        make_job(2, title="普通工程师", description="PyTorch CUDA"),
        make_job(3, title="PyTorch 岗位"),
        make_job(4, title="收益100%岗位"),
    ]
    ingest_run(jobs, "s1", rows, ts=T(1))
    upsert_texts(text, rows, ts=T(1))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.glob("*.db")}
    try:
        meta = {}
        result = search_jobs(jobs, text=term, text_conn=text, meta=meta)
        assert [r["id"] for r in result] == expected
        assert meta["total"] == len(expected)
        assert text.execute("PRAGMA user_version").fetchone()[0] == 1
        assert jobs.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        jobs.close()
        text.close()
    assert {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.glob("*.db")
    } == before


def test_querying_uncommitted_text_does_not_commit_the_callers_transaction(tmp_path):
    jobs = connect(tmp_path / "jobs.db", "jobs", defer_search_index=True)
    text = connect(tmp_path / "jd_text.db", "text", defer_search_index=True)
    row = make_job(1, description="PyTorch")
    ingest_run(jobs, "s1", [row], ts=T(1))
    upsert_texts(text, [row], ts=T(1))
    text.execute("UPDATE job_text SET description='TensorFlow'")
    try:
        assert [r["id"] for r in search_jobs(jobs, text="TensorFlow", text_conn=text)] == ["s1:1"]
        assert text.in_transaction
        text.rollback()
        assert text.execute("SELECT description FROM job_text").fetchone()[0] == "PyTorch"
    finally:
        jobs.close()
        text.close()


def test_repeated_terms_do_not_repeat_full_text_scans(jobs_db,text_db,monkeypatch):
    from jobradar.core import queries as q
    row=make_job(1,description='PyTorch CUDA')
    ingest_run(jobs_db,'s1',[row],ts=T(1))
    upsert_texts(text_db,[row],ts=T(1))
    original=q._jd_ids
    seen=[]
    def observed(conn,term,*args,**kwargs):
        seen.append(term)
        return original(conn,term,*args,**kwargs)
    monkeypatch.setattr(q,'_jd_ids',observed)
    assert q.search_jobs(jobs_db,text='PyTorch PyTorch CUDA PyTorch',text_conn=text_db)
    assert seen.count('PyTorch')==1


def test_overlong_full_text_query_is_rejected_before_scanning(jobs_db,text_db):
    with pytest.raises(ValueError,match='16'):
        search_jobs(jobs_db,text=' '.join(f'unique{i}' for i in range(17)),text_conn=text_db)
