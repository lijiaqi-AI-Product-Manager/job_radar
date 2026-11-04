import importlib.util
from dataclasses import asdict
from pathlib import Path

import pytest

from jobradar.models import Compliance, SourceConfig
from jobradar.pipeline.ingest import RunResult, ingest_run

spec = importlib.util.spec_from_file_location(
    "recover_sources", Path(__file__).parents[1] / "scripts/recover_sources.py")
recovery = importlib.util.module_from_spec(spec)
if spec.loader and Path(spec.origin).exists():
    spec.loader.exec_module(recovery)


def source(sid):
    return SourceConfig(id=sid, company=sid, adapter="example",
                        compliance=Compliance(checked_on="2026-11-04", robots="allowed", terms="public"))


def result(status="failed", reason="crawl budget exceeded", **kw):
    return asdict(RunResult(status, reason=reason, **kw))


@pytest.mark.parametrize("status,reason,eligible", [
    ("failed", "crawl budget exceeded", True),
    ("failed", "ReadTimeout: https://public.example/jobs", True),
    ("failed", "HTTPStatusError: HTTP 503 https://public.example/jobs", True),
    ("failed", "HTTPStatusError: HTTP 429 https://public.example/jobs", True),
    ("failed", "ComplianceError: robots unavailable", False),
    ("failed", "HTTPStatusError: HTTP 403 https://public.example/jobs", False),
    ("failed", "ValueError: incomplete_empty_page", False),
    ("failed", "ValueError: non_json", False),
    ("rejected", "job count dropped 100 -> 3", False),
    ("ok", None, False),
])
def test_retry_only_budget_and_explicit_transient_failures(status, reason, eligible):
    assert recovery.retryable(result(status, reason)) is eligible


def test_recovery_merges_full_context_and_accumulates_real_events(jobs_db, text_db):
    configs = [source(sid) for sid in ("ok", "retry", "blocked", "protected")]
    summary = {"ok": result("ok", None, opened=7), "retry": result(opened=2),
               "blocked": result(reason="ComplianceError: denied"),
               "protected": result("rejected", "empty result")}
    calls = []

    def fake_crawl(sources, *args, **kwargs):
        assert kwargs["preserve_source_order"] is True
        calls.append([s.id for s in sources])
        return {"retry": RunResult("ok", opened=3, closed=1)}

    merged, report = recovery.recover(configs, summary, jobs_db, text_db,
                                     budget_seconds=30, crawl_fn=fake_crawl)
    assert calls == [["retry"]]
    assert set(merged) == set(summary)
    assert merged["ok"]["opened"] == 7
    assert merged["retry"]["opened"] == 5 and merged["retry"]["closed"] == 1
    assert merged["protected"] == summary["protected"]
    assert report["before_bad"] == 3 and report["after_bad"] == 2
    assert report["recovered"] == ["retry"]


@pytest.mark.parametrize("summary", [{"a": result("ok", None)},
                                     {"a": result("ok", None), "b": result(), "extra": result()}])
def test_partial_or_unknown_sources_cannot_become_full_health(summary, jobs_db, text_db):
    with pytest.raises(ValueError, match="source set"):
        recovery.recover([source("a"), source("b")], summary, jobs_db, text_db,
                         budget_seconds=30, crawl_fn=lambda *a, **kw: pytest.fail("must not crawl"))


def test_rejected_sources_are_not_retried_or_written(jobs_db, text_db):
    ingest_run(jobs_db, "a", [], ts="2026-11-04T00:00:00Z", ok=False, error="original")
    before = list(jobs_db.execute("SELECT * FROM source_run"))
    merged, report = recovery.recover([source("a")], {"a": result("rejected", "drop")},
                                     jobs_db, text_db, budget_seconds=30,
                                     crawl_fn=lambda *a, **kw: pytest.fail("must not retry rejection"))
    assert list(jobs_db.execute("SELECT * FROM source_run")) == before
    assert merged["a"]["status"] == "rejected" and report["attempted"] == []


def test_recovery_only_baseline_keeps_original_observation_times(jobs_db):
    ingest_run(jobs_db, "a", [], ts="2026-11-02T00:00:00Z")
    ingest_run(jobs_db, "b", [], ts="2026-11-04T00:00:00Z", ok=False, error="crawl budget exceeded")
    baseline = recovery.baseline_from_db([source("a"), source("b"), source("never")], jobs_db)
    assert baseline["a"]["observed_at"] == "2026-11-02T00:00:00Z"
    assert baseline["a"]["opened"] == 0
    assert baseline["never"]["status"] == "failed"
    assert not recovery.retryable(baseline["never"])


def test_exhausted_per_source_budget_is_not_renewed_in_same_run(jobs_db, text_db):
    ingest_run(jobs_db, "a", [], ts="2026-11-04T00:00:00Z", ok=False,
               error="crawl budget exceeded", duration_s=3600)
    _, report = recovery.recover([source("a")], {"a": result()}, jobs_db, text_db,
                                 budget_seconds=30, source_budget=3600,
                                 crawl_fn=lambda *a, **kw: pytest.fail("source budget already spent"))
    assert report["attempted"] == [] and report["budget_spent"] == ["a"]


def test_recovery_uses_only_the_remaining_per_source_budget(jobs_db, text_db):
    ingest_run(jobs_db, "a", [], ts="2026-11-04T00:00:00Z", ok=False,
               error="crawl budget exceeded", duration_s=3000)

    def fake(sources, *args, **kw):
        assert kw["source_budget"] == 600
        return {"a": RunResult("ok")}

    recovery.recover([source("a")], {"a": result()}, jobs_db, text_db,
                     budget_seconds=30, source_budget=3600, crawl_fn=fake)


def test_recovery_stops_before_starting_another_batch_when_deadline_is_spent(jobs_db, text_db):
    clock = [100.0]
    configs = [source(f"a{i:02}") for i in range(25)]
    summary = {s.id: result() for s in configs}

    def fake(sources, *args, **kw):
        assert kw["budget_seconds"] <= 30
        clock[0] += 31
        return {s.id: RunResult("ok") for s in sources}

    merged, report = recovery.recover(configs, summary, jobs_db, text_db, budget_seconds=30,
                                     crawl_fn=fake, clock=lambda: clock[0])
    assert len(report["attempted"]) == 24 and report["after_bad"] == 1
    assert merged["a24"]["status"] == "failed"


def test_invalid_recovery_outcome_cannot_replace_full_summary(jobs_db, text_db):
    summary = {"a": result()}
    with pytest.raises(ValueError, match="source set"):
        recovery.recover([source("a")], summary, jobs_db, text_db, budget_seconds=30,
                         crawl_fn=lambda *a, **kw: {})
    assert summary == {"a": result()}


def test_budget_deferred_items_are_scheduled_but_not_counted_as_started(jobs_db, text_db):
    def fake(sources, *args, **kw):
        for sid, duration in (("a", 0), ("b", 2)):
            ingest_run(jobs_db, sid, [], ts=kw["ts"], ok=False,
                       error="crawl budget exceeded", duration_s=duration)
        return {s.id: RunResult("failed", reason="crawl budget exceeded") for s in sources}

    _, report = recovery.recover([source("a"), source("b")], {"a": result(), "b": result()},
                                 jobs_db, text_db, budget_seconds=30, crawl_fn=fake)
    assert report["scheduled"] == ["a", "b"]
    assert report["attempted"] == ["b"]
    assert report["not_started"] == ["a"]
    assert report["after_bad"] == 2
