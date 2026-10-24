from pathlib import Path

import httpx
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


def test_enrich_takes_grad_year_from_jd_when_title_has_none():
    j = _job(description="面向 2027 届毕业生", requirements="")
    _enrich(j)
    assert j.grad_year == 2027


def test_enrich_does_not_override_title_grad_year():
    j = _job(title="2027届-算法工程师", description="2026 届毕业生也可投递")
    _enrich(j)
    assert j.grad_year == 2027


def test_enrich_ignores_ambiguous_jd_grad_year():
    j = _job(description="2026届、2027届均可投递")
    _enrich(j)
    assert j.grad_year is None


def test_enrich_does_not_take_grad_year_for_social():
    j = _job(recruit_type="social", description="面向 2027 届毕业生")
    _enrich(j)
    assert j.grad_year is None
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
