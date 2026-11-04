import json

import httpx
import pytest

from helpers import T, make_job
from jobradar.adapters.base import Adapter, CrawlBudgetExceeded
from jobradar.models import Compliance, SourceConfig
from jobradar.pipeline.crawl import crawl


def config(**updates):
    values = {'id': 's1', 'company': '腾讯', 'adapter': 'hotjob',
              'params': {'detail_cache_hours': 168},
              'compliance': Compliance(checked_on='2026-11-04', robots='allowed', terms='公开岗位')}
    return SourceConfig(**{**values, **updates})


class Resumable(Adapter):
    id = 'hotjob'
    stop = True
    reads = []

    def fetch_raw(self):
        for index in (1, 2):
            cached = self.cached_texts.get(str(index))
            if not cached:
                self.reads.append(index)
            yield {'index': index, 'cached': cached}
            if self.stop:
                raise CrawlBudgetExceeded('crawl budget exceeded')

    def normalize(self, raw):
        cached = raw['cached']
        return make_job(raw['index'], description=cached['description'] if cached else '完整职责',
                        requirements=cached['requirements'] if cached else '本科及以上',
                        text_observed_at=cached['fetched_at'] if cached else None)


def test_partial_details_resume_without_changing_jobs_until_source_is_complete(jobs_db, text_db, tmp_path):
    Resumable.stop, Resumable.reads = True, []
    options = {'client_factory': lambda: httpx.Client(transport=httpx.MockTransport(lambda _: None)),
               'adapters': {'hotjob': Resumable}, 'sleep': lambda _: None,
               'detail_cache_dir': tmp_path / 'details'}
    first = crawl([config()], jobs_db, text_db, ts=T(1), **options)
    assert first['s1'].status == 'failed'
    assert jobs_db.execute('SELECT COUNT(*) FROM job').fetchone()[0] == 0
    assert text_db.execute('SELECT COUNT(*) FROM job_text').fetchone()[0] == 0
    Resumable.stop = False
    second = crawl([config()], jobs_db, text_db, ts=T(2), **options)
    assert second['s1'].status == 'ok'
    assert Resumable.reads == [1, 2]
    assert dict(text_db.execute('SELECT job_id,fetched_at FROM job_text')) == {'s1:1': T(1), 's1:2': T(2)}


def test_checkpoint_is_bound_to_source_identity_and_configuration(tmp_path):
    from jobradar.pipeline.detail_checkpoint import DetailCheckpoint
    root = tmp_path / 'details'
    store = DetailCheckpoint(root, config(), Resumable, T(1))
    store.record(make_job(1, description='原文'))
    assert '1' in DetailCheckpoint(root, config(), Resumable, T(2)).load()
    assert not DetailCheckpoint(root, config(company='另一公司'), Resumable, T(2)).load()


@pytest.mark.parametrize('timestamp', [T(20), '2026-09-01T00:00:00Z'])
def test_future_or_expired_checkpoint_is_not_reused(tmp_path, timestamp):
    from jobradar.pipeline.detail_checkpoint import DetailCheckpoint
    root = tmp_path / 'details'
    DetailCheckpoint(root, config(), Resumable, timestamp).record(make_job(1, description='原文'))
    assert not DetailCheckpoint(root, config(), Resumable, T(10)).load()


def test_malformed_checkpoint_does_not_break_source_refresh(tmp_path):
    from jobradar.pipeline.detail_checkpoint import DetailCheckpoint
    store = DetailCheckpoint(tmp_path / 'details', config(), Resumable, T(1))
    store.record(make_job(1, description='原文'))
    paths = list((tmp_path / 'details').rglob('*.json'))
    assert len(paths) == 1
    paths[0].write_text('{truncated', encoding='utf-8')
    assert not DetailCheckpoint(tmp_path / 'details', config(), Resumable, T(2)).load()


def test_checkpoint_contains_only_normalized_job_and_no_source_parameters(tmp_path):
    from jobradar.pipeline.detail_checkpoint import DetailCheckpoint
    source = config(params={'detail_cache_hours': 168, 'public_hint': 'not-a-job-field'})
    store = DetailCheckpoint(tmp_path / 'details', source, Resumable, T(1))
    store.record(make_job(1, description='原文'))
    raw = next((tmp_path / 'details').rglob('*.json')).read_text(encoding='utf-8')
    assert 'not-a-job-field' not in raw
    assert json.loads(raw)['job']['description'] == '原文'


def test_access_review_date_does_not_discard_unfinished_progress(tmp_path):
    from jobradar.pipeline.detail_checkpoint import DetailCheckpoint
    source = config()
    root = tmp_path / 'details'
    DetailCheckpoint(root, source, Resumable, T(1)).record(make_job(1, description='原文'))
    source.compliance.checked_on = source.compliance.checked_on.replace(day=5)
    assert '1' in DetailCheckpoint(root, source, Resumable, T(2)).load()


def test_optional_cache_write_failure_does_not_fail_an_otherwise_complete_source(jobs_db, text_db, tmp_path, monkeypatch):
    import jobradar.pipeline.detail_checkpoint as checkpoint
    Resumable.stop, Resumable.reads = False, []
    def unavailable(*args):
        raise OSError('cache unavailable')
    monkeypatch.setattr(checkpoint.os, 'replace', unavailable)
    results = crawl([config()], jobs_db, text_db, ts=T(1),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(lambda _: None)),
        adapters={'hotjob': Resumable}, sleep=lambda _: None, detail_cache_dir=tmp_path / 'details')
    assert results['s1'].status == 'ok'
    assert jobs_db.execute('SELECT COUNT(*) FROM job').fetchone()[0] == 2


def test_older_checkpoint_cannot_replace_newer_database_text(jobs_db, text_db, tmp_path):
    from jobradar.pipeline.detail_checkpoint import DetailCheckpoint
    from jobradar.pipeline.ingest import ingest_run, upsert_texts
    source = config()
    root = tmp_path / 'details'
    DetailCheckpoint(root, source, Resumable, T(1)).record(make_job(1, description='旧正文'))
    current = make_job(1, description='新正文')
    ingest_run(jobs_db, 's1', [current], ts=T(5))
    upsert_texts(text_db, [current], ts=T(5))
    Resumable.stop = False
    result = crawl([source], jobs_db, text_db, ts=T(6), detail_cache_dir=root,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(lambda _: None)),
        adapters={'hotjob': Resumable}, sleep=lambda _: None)
    assert result['s1'].status == 'ok'
    assert tuple(text_db.execute("SELECT description,fetched_at FROM job_text WHERE job_id='s1:1'").fetchone()) == ('新正文', T(5))
