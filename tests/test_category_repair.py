import importlib.util
import json
from pathlib import Path

import pytest

from helpers import T, make_job
from jobradar.pipeline.ingest import ingest_run, upsert_texts

spec = importlib.util.spec_from_file_location('category_repair', Path(__file__).parents[1] / 'scripts/repair_categories.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def seed(jobs, texts):
    rows = [make_job(1, title='财务专员', category='财务', subcategory=None, description='2027届本科毕业生'),
            make_job(2, title='岗位A1', category='未审核职类', subcategory=None),
            make_job(3, title='算法工程师', category='技术', subcategory='算法'),
            make_job(4, title='财务会计', category='职能', subcategory=None)]
    ingest_run(jobs, 's1', rows, ts=T(1))
    upsert_texts(texts, rows, ts=T(1))
    ingest_run(jobs, 's1', [], ts=T(2), ok=False, error='source unavailable')


def test_category_repair_previews_then_changes_only_derived_labels(jobs_db, text_db, tmp_path):
    seed(jobs_db, text_db)
    before = {row['id']:dict(row) for row in jobs_db.execute('SELECT * FROM job')}
    events = [tuple(row) for row in jobs_db.execute('SELECT * FROM job_event ORDER BY id')]
    runs = [tuple(row) for row in jobs_db.execute('SELECT * FROM source_run ORDER BY id')]
    bodies = [tuple(row) for row in text_db.execute('SELECT * FROM job_text ORDER BY job_id')]
    assert repair.repair_categories(jobs_db)['changed'] == 3
    assert {row['id']:dict(row) for row in jobs_db.execute('SELECT * FROM job')} == before
    audit = tmp_path / 'category-plan.json'
    result = repair.repair_categories(jobs_db, apply=True, audit_path=audit)
    assert result['changed'] == result['applied'] == 3
    assert json.loads(audit.read_text(encoding='utf-8'))['changes'][0]['before']['category'] == '财务'
    after = {row['id']:dict(row) for row in jobs_db.execute('SELECT * FROM job')}
    assert (after['s1:1']['category'], after['s1:1']['subcategory']) == ('职能', '财务审计')
    assert after['s1:2']['category'] is None
    assert after['s1:1']['grad_year'] == before['s1:1']['grad_year']
    for jid, row in after.items():
        assert {k:v for k,v in row.items() if k not in {'category','subcategory'}} == {
            k:v for k,v in before[jid].items() if k not in {'category','subcategory'}}
    assert [tuple(row) for row in jobs_db.execute('SELECT * FROM job_event ORDER BY id')] == events
    assert [tuple(row) for row in jobs_db.execute('SELECT * FROM source_run ORDER BY id')] == runs
    assert [tuple(row) for row in text_db.execute('SELECT * FROM job_text ORDER BY job_id')] == bodies
    assert repair.repair_categories(jobs_db, apply=True)['changed'] == 0


def test_category_repair_requires_a_new_audit_before_writing(jobs_db, text_db, tmp_path):
    seed(jobs_db, text_db)
    before = [tuple(row) for row in jobs_db.execute('SELECT * FROM job ORDER BY id')]
    with pytest.raises(ValueError, match='审计'):
        repair.repair_categories(jobs_db, apply=True)
    target = tmp_path / 'existing.json'
    target.write_text('original audit', encoding='utf-8')
    with pytest.raises(FileExistsError):
        repair.repair_categories(jobs_db, apply=True, audit_path=target)
    assert target.read_text(encoding='utf-8') == 'original audit'
    assert [tuple(row) for row in jobs_db.execute('SELECT * FROM job ORDER BY id')] == before


def test_category_repair_rolls_back_all_rows_when_evidence_changes(jobs_db, text_db, tmp_path, monkeypatch):
    seed(jobs_db, text_db)
    original = repair._write_audit

    def race(path, changes):
        original(path, changes)
        jobs_db.execute("UPDATE job SET title='源站已变更标题' WHERE id='s1:4'")
        jobs_db.commit()

    monkeypatch.setattr(repair, '_write_audit', race)
    with pytest.raises(ValueError, match='证据'):
        repair.repair_categories(jobs_db, apply=True, audit_path=tmp_path/'plan.json')
    assert jobs_db.execute("SELECT category FROM job WHERE id='s1:1'").fetchone()[0] == '财务'
    assert jobs_db.execute("SELECT title FROM job WHERE id='s1:4'").fetchone()[0] == '源站已变更标题'
