import sqlite3

import pytest

from helpers import T, make_job
from jobradar.core.queries import search_jobs
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.release_export import export_database
from jobradar.store.migrate import connect


@pytest.mark.parametrize('kind,name,version,table', [
    ('jobs', 'jobs.db', 2, 'job'), ('text', 'jd_text.db', 1, 'job_text'),
])
def test_published_database_is_readable_by_existing_clients_and_upgrades_again(tmp_path, kind, name, version, table):
    source, target = tmp_path / name, tmp_path / 'public' / name
    con = connect(source, kind)
    job = make_job(1, title='PyTorch 平台', description='大模型 PyTorch 研发')
    if kind == 'jobs':
        ingest_run(con, 's1', [job], ts=T(1))
    else:
        upsert_texts(con, [job], ts=T(1))
    con.close()
    export_database(source, target, kind)
    with sqlite3.connect(source) as original, sqlite3.connect(target) as published:
        assert published.execute('PRAGMA user_version').fetchone()[0] == version
        assert original.execute(f'SELECT * FROM {table}').fetchall() == published.execute(f'SELECT * FROM {table}').fetchall()
        assert not published.execute("SELECT name FROM sqlite_master WHERE name LIKE '%fts%'").fetchall()
        assert original.execute("SELECT name FROM sqlite_master WHERE name LIKE '%fts%'").fetchall()
        assert published.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    upgraded = connect(target, kind)
    assert upgraded.execute('PRAGMA user_version').fetchone()[0] > version
    if kind == 'jobs':
        assert search_jobs(upgraded, keyword='PyTorch')[0]['id'] == 's1:1'
    else:
        assert upgraded.execute("SELECT rowid FROM job_text_fts WHERE description LIKE '%大模型%'").fetchall()
    upgraded.close()


def test_unknown_schema_does_not_replace_a_previous_export(tmp_path):
    source, target = tmp_path / 'new.db', tmp_path / 'public.db'
    with sqlite3.connect(source) as con:
        con.execute('PRAGMA user_version=99')
    target.write_bytes(b'previous published database')
    with pytest.raises(ValueError):
        export_database(source, target, 'jobs')
    assert target.read_bytes() == b'previous published database'


def test_export_cannot_overwrite_the_working_database(tmp_path):
    source = tmp_path / 'jobs.db'
    with pytest.raises(ValueError):
        export_database(source, source, 'jobs')
