import sqlite3

import pytest

from jobradar.store.migrate import connect, migrate, migration_files


def test_fresh_db_is_at_latest_version(jobs_db):
    assert jobs_db.execute("PRAGMA user_version").fetchone()[0] == len(migration_files("jobs"))


def test_expected_tables(jobs_db, text_db):
    jobs = {r[0] for r in jobs_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"company", "job", "job_event", "source_run"} <= jobs
    texts = {r[0] for r in text_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "job_text" in texts


def test_migrate_is_idempotent(jobs_db):
    before = jobs_db.execute("PRAGMA user_version").fetchone()[0]
    assert migrate(jobs_db, "jobs") == before
    assert jobs_db.execute("PRAGMA user_version").fetchone()[0] == before


def test_database_newer_than_code_is_refused(tmp_path):
    p = tmp_path / "x.db"
    conn = connect(p, "jobs")
    conn.execute("PRAGMA user_version=999")
    conn.close()
    with pytest.raises(RuntimeError):
        connect(p, "jobs")


def _insert_company(conn):
    conn.execute("INSERT INTO company(name) VALUES ('A')")


def _job_args(**kw):
    base = dict(id="s:1", company_id=1, source_id="s", source_job_id="1", url="u", title="t",
                recruit_type="campus", first_seen="x", last_seen="x", content_hash="h")
    base.update(kw)
    cols = ",".join(base)
    return f"INSERT INTO job({cols}) VALUES ({','.join('?' * len(base))})", list(base.values())


def test_recruit_type_is_constrained(jobs_db):
    _insert_company(jobs_db)
    sql, args = _job_args(recruit_type="parttime")
    with pytest.raises(sqlite3.IntegrityError):
        jobs_db.execute(sql, args)


def test_source_job_is_unique(jobs_db):
    _insert_company(jobs_db)
    jobs_db.execute(*_job_args())
    sql, args = _job_args(id="s:1-dup")
    with pytest.raises(sqlite3.IntegrityError):
        jobs_db.execute(sql, args)


def test_foreign_keys_enforced(jobs_db):
    sql, args = _job_args(company_id=999)
    with pytest.raises(sqlite3.IntegrityError):
        jobs_db.execute(sql, args)
