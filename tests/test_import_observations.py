"""离线复验：恢复完整观测不能覆盖较新结果或绕过入库保护。"""

import copy
import importlib.util
from pathlib import Path

import pytest

from helpers import make_job
from jobradar import __version__
from jobradar.models import SourceConfig
from jobradar.pipeline.ingest import ingest_run

spec = importlib.util.spec_from_file_location(
    "import_observations", Path(__file__).resolve().parents[1] / "scripts/import_verified_crawl.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)

OLD = "2026-11-02T08:00:00Z"
OBSERVED = "2026-11-02T09:00:00Z"
NOW = "2026-11-02T10:00:00Z"


def sample(source_id="s1"):
    return SourceConfig(id=source_id, company="示例公司", adapter="jysd", enabled=False,
                        params={"host": "career.example.edu.cn"}).model_copy(update={"enabled": True})


def payload(*sources):
    return {"schema_version": 1, "application_version": __version__, "captured_at": OBSERVED,
            "sources": [{"source_id": s.id, "observed_at": OBSERVED, "completed_at": OBSERVED,
                         "complete": True, "source_config_sha256": recovery.config_sha256(s),
                         "jobs": [make_job(1, source_id=s.id, company=s.company,
                                           url="https://career.example.edu.cn/campus/view/id/1",
                                           grad_year=2027, description="公开岗位职责").model_dump()]}
                        for s in sources]}


def state(jobs, texts):
    return tuple(tuple(tuple(row) for row in conn.execute(f"SELECT * FROM {table}"))
                 for conn, table in ((jobs, "job"), (jobs, "source_run"), (jobs, "job_event"),
                                     (texts, "job_text")))


def test_preserve_first_seen_other_sources_and_original_observation(jobs_db, text_db):
    source = sample()
    ingest_run(jobs_db, source.id, [make_job(1)], ts=OLD)
    ingest_run(jobs_db, "unrelated", [make_job(2, source_id="unrelated")], ts=OLD)
    old_other = tuple(jobs_db.execute("SELECT * FROM job WHERE source_id='unrelated'").fetchone())
    result = recovery.apply_observations(jobs_db, text_db, payload(source), [source], now=NOW)
    row = jobs_db.execute("SELECT * FROM job WHERE id='s1:1'").fetchone()
    assert (row["first_seen"], row["last_seen"], row["grad_year"]) == (OLD, OBSERVED, 2027)
    assert tuple(jobs_db.execute("SELECT * FROM job WHERE source_id='unrelated'").fetchone()) == old_other
    assert text_db.execute("SELECT fetched_at FROM job_text").fetchone()[0] == OBSERVED
    assert result["accepted_sources"] == 1
    before = state(jobs_db, text_db)
    assert recovery.apply_observations(jobs_db, text_db, payload(source), [source], now=NOW)["skipped_sources"] == 1
    assert state(jobs_db, text_db) == before


@pytest.mark.parametrize("change", [
    lambda p: p.update(schema_version=2),
    lambda p: p.update(application_version="0.0.0"),
    lambda p: p["sources"][0].update(complete=False),
    lambda p: p["sources"][0].update(source_config_sha256="0" * 64),
    lambda p: p["sources"][0].update(jobs=[]),
    lambda p: p["sources"][0].update(observed_at="2026-10-30T09:00:00Z"),
    lambda p: p["sources"][0].update(observed_at="2026-11-03T09:00:00Z"),
    lambda p: p["sources"][0].update(completed_at=OLD),
    lambda p: p["sources"][0]["jobs"][0].update(source_id="other"),
    lambda p: p["sources"][0]["jobs"][0].update(company="其他主体"),
    lambda p: p["sources"][0]["jobs"][0].update(url="https://other.example.org/1"),
    lambda p: p["sources"][0]["jobs"][0].update(url="https://user:pass@career.example.edu.cn/1"),
    lambda p: p["sources"][0]["jobs"][0].update(apply_end="2026-02-30"),
    lambda p: p["sources"][0]["jobs"][0].update(recruit_type="social"),
    lambda p: p["sources"][0]["jobs"].append(copy.deepcopy(p["sources"][0]["jobs"][0])),
    lambda p: p["sources"].append(copy.deepcopy(p["sources"][0])),
])
def test_invalid_payload_does_not_write(jobs_db, text_db, change):
    source = sample()
    value = payload(source)
    change(value)
    before = state(jobs_db, text_db)
    with pytest.raises(ValueError):
        recovery.apply_observations(jobs_db, text_db, value, [source], now=NOW)
    assert state(jobs_db, text_db) == before


def test_older_observation_cannot_rewind_source(jobs_db, text_db):
    source = sample()
    ingest_run(jobs_db, source.id, [make_job(1)], ts=NOW)
    before = state(jobs_db, text_db)
    with pytest.raises(ValueError, match="newer"):
        recovery.apply_observations(jobs_db, text_db, payload(source), [source], now=NOW)
    assert state(jobs_db, text_db) == before


def test_replay_remains_idempotent_when_ingest_preserves_known_deadline(jobs_db, text_db):
    source = sample()
    ingest_run(jobs_db, source.id, [make_job(1, apply_end="2027-01-01")], ts=OLD)
    value = payload(source)
    recovery.apply_observations(jobs_db, text_db, value, [source], now=NOW)
    before = state(jobs_db, text_db)
    assert recovery.apply_observations(jobs_db, text_db, value, [source], now=NOW)["skipped_sources"] == 1
    assert state(jobs_db, text_db) == before


def test_rejected_second_source_rolls_back_entire_batch(jobs_db, text_db):
    first, second = sample(), sample("s2")
    ingest_run(jobs_db, "s2", [make_job(i, source_id="s2") for i in range(20)], ts=OLD)
    before = state(jobs_db, text_db)
    with pytest.raises(ValueError, match="rejected"):
        recovery.apply_observations(jobs_db, text_db, payload(first, second), [first, second], now=NOW)
    assert state(jobs_db, text_db) == before


def test_unknown_or_disabled_source_is_rejected(jobs_db, text_db):
    source = sample()
    for configs in ([], [source.model_copy(update={"enabled": False})]):
        with pytest.raises(ValueError):
            recovery.apply_observations(jobs_db, text_db, payload(source), configs, now=NOW)


def test_existing_verified_public_host_supports_fixed_host_adapters(jobs_db, text_db):
    source = sample("tencent").model_copy(update={"adapter": "tencent", "params": {}})
    old = make_job(1, source_id=source.id, company=source.company, url="https://careers.tencent.com/jobdesc.html?positionId=1")
    ingest_run(jobs_db, source.id, [old], ts=OLD)
    value = payload(source)
    value["sources"][0]["jobs"][0]["url"] = old.url
    assert recovery.apply_observations(jobs_db, text_db, value, [source], now=NOW)["accepted_sources"] == 1
    changed = payload(source)
    changed["sources"][0]["jobs"][0]["url"] = "https://unverified.example.org/1"
    with pytest.raises(ValueError):
        recovery.apply_observations(jobs_db, text_db, changed, [source], now=NOW)


def test_future_cached_text_timestamp_is_rejected_before_import(jobs_db, text_db):
    source = sample()
    value = payload(source)
    value["sources"][0]["jobs"][0]["text_observed_at"] = NOW
    before = state(jobs_db, text_db)
    with pytest.raises(ValueError):
        recovery.apply_observations(jobs_db, text_db, value, [source], now=NOW)
    assert state(jobs_db, text_db) == before
