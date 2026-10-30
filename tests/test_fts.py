import sqlite3

import pytest

from helpers import T, make_job
from jobradar.core.queries import search_jobs
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import MIGRATIONS_ROOT, migrate


@pytest.mark.parametrize("kind,version,table,column,text", [
    ("jobs", 2, "job_fts", "title", "大模型研发"),
    ("text", 1, "job_text_fts", "description", "大模型研发"),
])
def test_upgrade_backfills_existing_content_and_preserves_data(kind, version, table, column, text):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    for path in sorted((MIGRATIONS_ROOT / kind).glob("*.sql"))[:version]:
        con.executescript(path.read_text(encoding="utf-8"))
    con.execute(f"PRAGMA user_version={version}")
    job = make_job(1, title=text, description=text)
    if kind == "jobs":
        ingest_run(con, "s1", [job], ts=T(1))
    else:
        upsert_texts(con, [job], ts=T(1))
    migrate(con, kind)
    assert con.execute(f"SELECT rowid FROM {table} WHERE {column} LIKE ?", ("%大模型%",)).fetchall()
    base = "job" if kind == "jobs" else "job_text"
    assert con.execute(f"SELECT COUNT(*) FROM {base}").fetchone()[0] == 1
    con.execute(f"INSERT INTO {table}({table}, rank) VALUES ('integrity-check', 1)")
    con.close()


def test_fts_is_used_for_jd_and_title_and_keeps_multi_term_semantics(jobs_db, text_db):
    jobs = [make_job(1, title="框架研发", description="精通 PyTorch，熟悉CUDA"),
            make_job(2, title="PyTorch 平台", requirements="CUDA 优化"),
            make_job(3, title="无关岗位", requirements="PyTorch")]
    ingest_run(jobs_db, "s1", jobs, ts=T(1))
    upsert_texts(text_db, jobs, ts=T(1))
    trace_jobs, trace_text = [], []
    jobs_db.set_trace_callback(trace_jobs.append)
    text_db.set_trace_callback(trace_text.append)
    rows = search_jobs(jobs_db, text="pytorch CUDA", text_conn=text_db)
    assert [r["id"] for r in rows] == ["s1:1", "s1:2"]
    assert any("job_fts" in sql for sql in trace_jobs)
    assert any("job_text_fts" in sql for sql in trace_text)


@pytest.mark.parametrize("term,expected", [
    ("大模型", ["s1:1"]), ("算法", ["s1:1", "s1:2"]), ("Go", ["s1:2"]),
    ("C++", ["s1:1"]), ("90%", ["s1:1"]), ("data_base", ["s1:1"]),
    ('"引号"', ["s1:1"]), ("R&D", ["s1:1"]), ("pytorch", ["s1:1"]),
    (r"C:\foo", ["s1:1"]), ("no-match", []),
])
def test_fts_preserves_literal_substring_and_short_chinese_queries(jobs_db, text_db, term, expected):
    jobs = [make_job(1, title="岗位一", description='大模型算法 PyTorch C++ R&D 90% data_base "引号" C:\\foo'),
            make_job(2, title="岗位二", description="算法 Go Java database 90X")]
    ingest_run(jobs_db, "s1", jobs, ts=T(1))
    upsert_texts(text_db, jobs, ts=T(1))
    assert [r["id"] for r in search_jobs(jobs_db, text=term, text_conn=text_db)] == expected


def test_fts_triggers_follow_updates_deletes_and_rollback(jobs_db, text_db):
    job = make_job(1, title="PyTorch 开发", description="TensorFlow 平台")
    ingest_run(jobs_db, "s1", [job], ts=T(1))
    upsert_texts(text_db, [job], ts=T(1))
    assert search_jobs(jobs_db, text="TensorFlow", text_conn=text_db)
    upsert_texts(text_db, [make_job(1, description="JAX 平台")], ts=T(2))
    assert search_jobs(jobs_db, text="TensorFlow", text_conn=text_db) == []
    ingest_run(jobs_db, "s1", [make_job(1, title="Scala 开发", description="JAX 平台")], ts=T(2))
    assert search_jobs(jobs_db, text="PyTorch", text_conn=text_db) == []
    text_db.execute("UPDATE job_text SET description='PyTorch' WHERE job_id='s1:1'")
    text_db.rollback()
    assert search_jobs(jobs_db, text="PyTorch", text_conn=text_db) == []
    with text_db:
        text_db.execute("DELETE FROM job_text WHERE job_id='s1:1'")
    assert search_jobs(jobs_db, text="JAX", text_conn=text_db) == []
    assert search_jobs(jobs_db, text="Scala", text_conn=text_db)


def test_search_keeps_working_with_unmigrated_databases():
    jobs, text = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    jobs.row_factory = text.row_factory = sqlite3.Row
    for kind, con in (("jobs", jobs), ("text", text)):
        old_files = sorted((MIGRATIONS_ROOT / kind).glob("*.sql"))[:2 if kind == "jobs" else 1]
        for path in old_files:
            con.executescript(path.read_text(encoding="utf-8"))
    job = make_job(1, title="大模型研发", description="PyTorch")
    ingest_run(jobs, "s1", [job], ts=T(1))
    upsert_texts(text, [job], ts=T(1))
    assert [r["id"] for r in search_jobs(jobs, text="PyTorch 大模型", text_conn=text)] == ["s1:1"]
    jobs.close()
    text.close()
