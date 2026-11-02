import gzip
import threading
import time

import httpx
import pytest

from jobradar.adapters.base import CrawlBudgetExceeded, make_client
from jobradar.compliance import RobotsPolicy

DEADLINE='jobradar_deadline'
LIMIT='jobradar_response_limit'


class Clock:
    def __init__(self):
        self.now=0.0

    def read(self):
        return self.now

    def sleep(self,seconds):
        self.now+=seconds


def test_origin_rate_wait_stops_at_request_deadline(monkeypatch):
    clock=Clock()
    monkeypatch.setattr(time,'monotonic',clock.read)
    seen=[]

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(404) if req.url.path=='/robots.txt' else httpx.Response(200,text='jobs')

    policy=RobotsPolicy(clock=clock.read,sleep=clock.sleep)
    with make_client(httpx.MockTransport(handler),policy=policy) as client:
        client.get('https://example.test/jobs')
        with pytest.raises(CrawlBudgetExceeded):
            client.get('https://example.test/next',extensions={DEADLINE:clock.now+.2})
    assert seen==['/robots.txt','/jobs']
    assert clock.now==pytest.approx(1.2)


@pytest.mark.parametrize('robots',[False,True])
def test_trickling_body_cannot_extend_absolute_deadline(monkeypatch,robots):
    clock=Clock()
    monkeypatch.setattr(time,'monotonic',clock.read)
    seen=[]

    class Drip(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(5):
                clock.now+=.4
                yield b' ' if robots else b'x'

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200,stream=Drip())

    policy=RobotsPolicy(clock=clock.read,sleep=clock.sleep) if robots else None
    with make_client(httpx.MockTransport(handler),policy=policy) as client,pytest.raises(CrawlBudgetExceeded):
        client.get('https://example.test/jobs',extensions={DEADLINE:1.0})
    assert seen==['/robots.txt' if robots else '/jobs']
    assert clock.now<=1.2+.00001


def test_wait_for_another_robots_probe_has_a_deadline():
    policy=RobotsPolicy()
    lock=threading.Lock()
    lock.acquire()
    policy._locks['https://example.test']=lock
    release=threading.Timer(.2,lock.release)
    release.start()
    seen=[]
    try:
        with make_client(httpx.MockTransport(lambda r:seen.append(r.url.path) or httpx.Response(404)),policy=policy) as client:
            with pytest.raises(CrawlBudgetExceeded):
                client.get('https://example.test/jobs',extensions={DEADLINE:time.monotonic()+.03})
    finally:
        release.join()
    assert seen==[]


def test_response_size_bound_is_checked_before_parsing():
    with make_client(httpx.MockTransport(lambda _:httpx.Response(200,content=b'x'*32))) as client:
        with pytest.raises(RuntimeError,match='响应.*上限'):
            client.get('https://example.test/jobs',extensions={LIMIT:8})


def test_budget_reached_in_last_normalization_cannot_be_reported_as_success(monkeypatch):
    from jobradar.adapters.example import ExampleAdapter
    from jobradar.models import Job, SourceConfig

    clock=Clock()
    monkeypatch.setattr(time,'monotonic',clock.read)

    class LastDetail(ExampleAdapter):
        def fetch_raw(self):
            return iter([{}])

        def normalize(self,raw):
            clock.now=2
            return Job(source_id='s',source_job_id='1',company='样本',title='工程师',url='https://example.test/job/1',recruit_type='campus')

    with make_client(httpx.MockTransport(lambda _:None)) as client:
        adapter=LastDetail(SourceConfig(id='s',company='样本',adapter='example',enabled=False),client)
        adapter._crawl_deadline=1
        with pytest.raises(CrawlBudgetExceeded):
            list(adapter.fetch_all())


def test_gzip_header_trickle_is_bounded_before_decoder_emits_bytes(monkeypatch):
    clock=Clock()
    monkeypatch.setattr(time,'monotonic',clock.read)

    class DripGzip(httpx.SyncByteStream):
        def __iter__(self):
            for value in gzip.compress(b'x'*1000):
                clock.now+=.4
                yield bytes([value])

    with make_client(httpx.MockTransport(lambda _:httpx.Response(200,headers={'content-encoding':'gzip'},stream=DripGzip()))) as client:
        with pytest.raises(CrawlBudgetExceeded):
            client.get('https://example.test/jobs',extensions={DEADLINE:1})
    assert clock.now<=1.2+.00001


def test_decoded_body_cannot_bypass_size_limit_with_compression():
    class Compressed(httpx.SyncByteStream):
        def __iter__(self):
            yield gzip.compress(b'x'*4096)

    with make_client(httpx.MockTransport(lambda _:httpx.Response(200,headers={'content-encoding':'gzip'},stream=Compressed()))) as client:
        with pytest.raises(RuntimeError,match='响应.*上限'):
            client.get('https://example.test/jobs',extensions={LIMIT:32})


def test_oversized_robots_is_unverified_and_never_allows_content():
    from jobradar.compliance import ComplianceError

    seen=[]

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200,text='User-agent: *\n#'+('x'*600000))

    with make_client(httpx.MockTransport(handler),policy=RobotsPolicy()) as client:
        with pytest.raises(ComplianceError,match='无法核实'):
            client.get('https://example.test/jobs')
    assert seen==['/robots.txt']


def test_shared_policy_honors_a_stricter_caller_interval():
    clock=Clock()
    seen=[]

    def handler(req):
        seen.append(clock.now)
        return httpx.Response(404) if req.url.path=='/robots.txt' else httpx.Response(200)

    with make_client(httpx.MockTransport(handler),policy=RobotsPolicy(clock=clock.read,sleep=clock.sleep,min_interval=2)) as client:
        client.get('https://example.test/jobs')
        client.get('https://example.test/next')
    assert seen[-1]-seen[-2]>=2
