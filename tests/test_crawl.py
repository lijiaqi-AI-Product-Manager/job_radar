from pathlib import Path

import httpx
import yaml

from helpers import T
from jobradar.adapters.example import ExampleAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig
from jobradar.pipeline.crawl import crawl

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
