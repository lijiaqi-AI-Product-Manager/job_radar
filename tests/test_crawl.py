from pathlib import Path

import httpx
import pytest
import yaml

from helpers import T
from jobradar.adapters.example import ExampleAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import Job, SourceConfig
from jobradar.pipeline.crawl import _enrich, crawl

FX = Path(__file__).parent / "fixtures" / "example"


def example_source(**kw):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data.update(kw)
    return SourceConfig(**data)


def replay_client():
    return httpx.Client(transport=ReplayTransport(FX))


class Boom(ExampleAdapter):
    def fetch_raw(self):
        raise RuntimeError("site changed")


def test_crawl_ingests_jobs_and_texts(jobs_db, text_db):
    res = crawl([example_source()], jobs_db, text_db, ts=T(1), client_factory=replay_client,
                adapters={"example": ExampleAdapter}, sleep=lambda s: None)
    assert res["example-corp"].opened == 2
    assert text_db.execute("SELECT COUNT(*) FROM job_text").fetchone()[0] == 2
    cats = dict(jobs_db.execute("SELECT source_job_id, subcategory FROM job").fetchall())
    assert cats == {"101": "后端", "102": "算法"}  # 适配器未给职类 -> crawl 按 taxonomy 归类


def test_crawl_records_per_source_duration(jobs_db, text_db):
    """每源耗时写进 source_run.duration_s（这一列以前永远是 NULL，慢源无法定位）。"""
    crawl([example_source()], jobs_db, text_db, ts=T(1), client_factory=replay_client,
          adapters={"example": ExampleAdapter}, sleep=lambda s: None)
    d = jobs_db.execute("SELECT duration_s FROM source_run WHERE source_id='example-corp'").fetchone()[0]
    assert d is not None and d >= 0


def test_crawl_records_duration_for_failed_source(jobs_db, text_db):
    """失败也要记耗时：超时的源正是最需要被看见的那类。"""
    crawl([example_source(id="broken", adapter="boom")], jobs_db, text_db, ts=T(1),
          client_factory=replay_client, adapters={"boom": Boom}, sleep=lambda s: None)
    d = jobs_db.execute("SELECT duration_s FROM source_run WHERE source_id='broken'").fetchone()[0]
    assert d is not None


def test_adapter_error_is_a_failed_run_and_isolated(jobs_db, text_db):
    sources = [example_source(), example_source(id="broken", adapter="boom")]
    res = crawl(sources, jobs_db, text_db, ts=T(1), client_factory=replay_client,
                adapters={"example": ExampleAdapter, "boom": Boom}, sleep=lambda s: None)
    assert res["example-corp"].status == "ok"
    assert res["broken"].status == "failed" and "site changed" in res["broken"].reason


def test_unknown_adapter_and_disabled_sources(jobs_db, text_db):
    sources = [example_source(id="x", adapter="nope"), example_source(id="off", enabled=False)]
    res = crawl(sources, jobs_db, text_db, ts=T(1), client_factory=replay_client,
                adapters={"example": ExampleAdapter}, sleep=lambda s: None)
    assert res["x"].status == "failed"
    assert "off" not in res


def test_unmatched_request_counts_as_failure(jobs_db, text_db, tmp_path):
    # 回放里没有这个请求 -> 适配器异常 -> 失败，而不是让整次 crawl 崩溃
    (tmp_path / "manifest.json").write_text("[]")
    res = crawl([example_source()], jobs_db, text_db, ts=T(1),
                client_factory=lambda: httpx.Client(transport=ReplayTransport(tmp_path)),
                adapters={"example": ExampleAdapter}, sleep=lambda s: None)
    assert res["example-corp"].status == "failed"


def _job(**kw):
    base = dict(source_id="s1", source_job_id="1", company="某公司", url="https://x/1",
                title="算法工程师", recruit_type="campus")
    return Job(**{**base, **kw})


def test_enrich_never_touches_grad_year():
    """届别由适配器一人说了算，_enrich 不许从 JD 再补一次（2026-10-26 字节跳动实测）。

    反例：2023 年挂到现在的实习岗，JD 写着"2023届"。适配器按发布时间判定 JD 已过期、
    主动留空，_enrich 却用 grad_year_from_jd 补成 2027 —— 于是"2027届在招"出现在一个
    2023 年的岗位上。所以这里断言的正是"什么都不做"。
    """
    for kw in (
        {"description": "面向 2027 届毕业生", "requirements": ""},
        {"title": "2027届-算法工程师", "description": "2026 届毕业生也可投递"},
        {"description": "2026届、2027届均可投递"},
        {"recruit_type": "social", "description": "面向 2027 届毕业生"},
    ):
        j = _job(**kw)
        _enrich(j)
        assert j.grad_year is None, kw


def test_enrich_still_fills_category_and_cities():
    j = _job(title="后端开发工程师（深圳）")
    _enrich(j)
    assert j.category == "技术"
    assert j.cities == ["深圳"]
def test_budget_exceeded_skips_remaining_sources(jobs_db, text_db):
    """整轮采集有预算：超时后剩余源标记失败，不拖到 workflow 上限（2026-10-22 daily 跑了 75 分钟+）。"""
    sources = [example_source(), example_source(id="later")]
    res = crawl(sources, jobs_db, text_db, ts=T(1), client_factory=replay_client,
                adapters={"example": ExampleAdapter}, sleep=lambda s: None, budget_seconds=-1)
    assert set(res) == {"example-corp", "later"}
    for r in res.values():
        assert r.status == "failed" and "budget" in (r.reason or "")

def test_site_key_separates_tenants_but_keeps_shared_hosts_serial():
    """并行单位是「适配器 + 站点」：北森租户各在不同子域可以并行，同一 host 必须串行。"""
    from jobradar.models import Compliance
    from jobradar.pipeline.crawl import _site_key

    compliance = Compliance(checked_on="2026-10-20", robots="allowed", terms="t")

    def src(sid, **params):
        return SourceConfig(id=sid, company="某公司", adapter="beisen", params=params, compliance=compliance)

    assert _site_key(src("a", tenant="acme")) == "acme"
    assert _site_key(src("b", tenant="beta")) == "beta"          # 不同租户 → 不同组 → 可并行
    assert _site_key(src("c", host="wecruit.hotjob.cn", tenant="SU1")) == "wecruit.hotjob.cn"
    assert _site_key(src("d", host="wecruit.hotjob.cn", tenant="SU2")) == "wecruit.hotjob.cn"  # 同站 → 同组


class Recording(ExampleAdapter):
    """按开始顺序记下被调度的源（每源单独一个站点组）。"""

    order: list[str] = []

    def fetch_raw(self):
        Recording.order.append(self.source.id)
        return super().fetch_raw()


def test_crawl_rotates_site_group_order_by_seed(jobs_db, text_db):
    """站点组比预算多得多，固定顺序会让尾部源永远跑不到：不同日期种子要换一批排头。"""
    def run(seed):
        Recording.order = []
        sources = [example_source(id=f"s{i}", params={"tenant": f"t{i}", "path": "jobs"})
                   for i in range(8)]
        crawl(sources, jobs_db, text_db, ts=T(1), client_factory=replay_client,
              adapters={"example": Recording}, sleep=lambda s: None,
              max_workers=1, order_seed=seed)
        return list(Recording.order)

    a, b = run(1), run(2)
    assert sorted(a) == sorted(b) == [f"s{i}" for i in range(8)]  # 每个源都跑到，只是顺序不同
    assert a != b


def test_budget_interrupts_an_adapter_between_pages_without_ingesting_partial_results(
    jobs_db, text_db, monkeypatch
):
    import jobradar.pipeline.crawl as module

    clock = [100.0]
    requests = []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class Paged(ExampleAdapter):
        def fetch_raw(self):
            for page in range(20):
                self.request_json("GET", "https://example.invalid/page", params={"page": page})
                yield {"id": str(page), "title": "工程师"}

        def normalize(self, raw):
            return Job(source_id=self.source.id, source_job_id=raw["id"], company="示例公司",
                       url="https://example.invalid/job", title=raw["title"], recruit_type="campus")

    def respond(request):
        requests.append(request)
        clock[0] += 2
        return httpx.Response(200, json={})

    results = crawl([example_source()], jobs_db, text_db, ts=T(1),
                    client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
                    adapters={"example": Paged}, sleep=lambda _: None,
                    max_workers=1, budget_seconds=3)
    assert len(requests) == 2
    assert requests[1].extensions["timeout"]["read"] <= 1
    result = results["example-corp"]
    assert result.status == "failed" and result.reason == "crawl budget exceeded"
    assert jobs_db.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 0
    assert text_db.execute("SELECT COUNT(*) FROM job_text").fetchone()[0] == 0


def test_shared_host_sources_rotate_instead_of_always_deferring_the_same_tail(jobs_db, text_db):
    class OrderOnly(ExampleAdapter):
        order = []

        def fetch_raw(self):
            self.order.append(self.source.id)
            return iter(())

    def run(seed):
        OrderOnly.order = []
        sources = [example_source(id=f"s{i}", params={"host": "shared.invalid"}) for i in range(8)]
        crawl(sources, jobs_db, text_db, ts=T(1), adapters={"example": OrderOnly},
              client_factory=lambda: httpx.Client(transport=httpx.MockTransport(lambda _: None)),
              sleep=lambda _: None, max_workers=1, order_seed=seed)
        return list(OrderOnly.order)

    a, b = run(1), run(2)
    assert sorted(a) == sorted(b) == [f"s{i}" for i in range(8)]
    assert a == run(1)
    assert a != b


@pytest.mark.parametrize("retry", [False, True])
def test_rate_limit_and_retry_waits_stop_at_the_budget(monkeypatch, retry):
    import jobradar.adapters.base as base

    clock = [100.0]
    waits, requests = [], []
    monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])

    def pause(seconds):
        waits.append(seconds)
        clock[0] += seconds

    def respond(request):
        requests.append(request)
        return httpx.Response(503, json={})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        adapter = ExampleAdapter(example_source(), client, sleep=pause)
        adapter._crawl_deadline = 100.25
        adapter._last_request = 0.0 if retry else 100.0
        with pytest.raises(base.CrawlBudgetExceeded):
            adapter.request_json("GET", "https://example.invalid/page")
    assert waits == [0.25]
    assert len(requests) == int(retry)
