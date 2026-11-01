import sqlite3
from contextlib import closing

import pytest

from jobradar import cli
from jobradar.store.migrate import connect


@pytest.mark.parametrize("kind,name,ddl", [
    ("jobs", "jobs.db", "CREATE TABLE job(id,source_id,company_id,title,closed_at);"
     "CREATE TABLE company(id,name);CREATE TABLE source_run(source_id,status,ts);"
     "CREATE TABLE job_event(job_id,ts,type);PRAGMA user_version=2;"),
    ("text", "jd_text.db", "CREATE TABLE job_text(job_id,description,requirements);PRAGMA user_version=1;"),
    ("calendar", "calendar.db", "CREATE TABLE entry(id,origin,group_name,apply_end);"
     "CREATE TABLE target(name);CREATE TABLE build(ts);PRAGMA user_version=1;"),
])
def test_incomplete_declared_schema_is_rejected_before_install(tmp_path, kind, name, ddl):
    destination = tmp_path / name
    connect(destination, kind, defer_search_index=True).close()
    original = destination.read_bytes()
    incoming = tmp_path / "incoming.db"
    with closing(sqlite3.connect(incoming)) as conn:
        conn.executescript(ddl)
    assert not cli._local_db_ok(incoming, name)
    with pytest.raises(ValueError):
        cli._install(incoming, name, False, destination)
    assert destination.read_bytes() == original


@pytest.mark.parametrize("kind,name", [("jobs", "jobs.db"), ("text", "jd_text.db"), ("calendar", "calendar.db")])
def test_full_supported_schema_is_valid(tmp_path, kind, name):
    path = tmp_path / name
    connect(path, kind, defer_search_index=True).close()
    assert cli._local_db_ok(path, name)


def test_public_calendar_with_optional_evidence_table_is_valid(tmp_path):
    path = tmp_path / "calendar.db"
    with closing(connect(path, "calendar")) as conn:
        conn.execute("PRAGMA user_version=1")
    assert cli._local_db_ok(path)


@pytest.mark.parametrize("removed", ["UNIQUE (source_id, source_job_id)", "CHECK (recruit_type IN ('campus', 'intern', 'social'))"])
def test_full_columns_without_declared_constraints_are_rejected(tmp_path, removed):
    from jobradar.store.migrate import migration_files

    path = tmp_path / 'jobs.db'
    with closing(sqlite3.connect(path)) as conn:
        sql = migration_files('jobs')[0].read_text(encoding='utf-8')
        sql = sql.replace(',\n    ' + removed, '') if removed.startswith('UNIQUE') else sql.replace(removed, '')
        conn.executescript(sql + '\nPRAGMA user_version=1;')
    assert not cli._local_db_ok(path)
