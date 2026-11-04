"""默认诊断有界，优先展示影响岗位最多的来源，完整明细可主动展开。"""

import json
from contextlib import closing

import pytest

from helpers import T, make_job
from jobradar import cli
from jobradar.core import queries as q
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect


@pytest.fixture
def unhealthy(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    with closing(connect(tmp_path / "jobs.db", "jobs")) as conn:
        ingest_run(conn, "fixture", [make_job(1, source_id="fixture")], ts=T(1))
    rows = [dict(source_id=f"source-{i:02}", last_status="failed", last_run=T(1), last_ok=None,
                 stale=True, open_jobs=i, duration_s=1, age_hours=None, error="unavailable") for i in range(30)]
    monkeypatch.setattr(q, "data_status", lambda *a, **kw: rows)
    return rows


def test_summary_orders_by_affected_jobs_and_limits_default_output(unhealthy):
    summary = q.data_status_summary(unhealthy)
    assert summary["counts"]["sources"] == 30
    assert len(summary["problems"]) == 10 and summary["omitted_problems"] == 20
    assert summary["problems"][0]["source_id"] == "source-29"
    assert q.source_freshness(unhealthy)["stale_sources"][0]["source_id"] == "source-29"


@pytest.mark.parametrize("verbose", [False, True])
def test_doctor_has_compact_default_and_explicit_full_details(unhealthy, capsys, verbose):
    cli.main(["doctor", *(["--verbose"] if verbose else [])])
    result = json.loads(capsys.readouterr().out)
    details = result["source_health"]
    assert details["counts"]["stale"] == 30
    assert len(details["stale_sources"]) == (30 if verbose else 10)
    assert details["omitted_stale_sources"] == (0 if verbose else 20)


@pytest.mark.parametrize("verbose", [False, True])
def test_mcp_status_keeps_counts_and_bounds_both_detail_lists(unhealthy, verbose):
    mcp = pytest.importorskip("jobradar.mcp_server")
    result = mcp.data_status(verbose=verbose)
    assert len(result["failing"]) == (30 if verbose else 10)
    if verbose:
        assert len(result["results"]) == 30
    else:
        assert result["counts"]["sources"] == 30
        assert len(result["problems"]) == 10
        assert result["problems"][0]["source_id"] == "source-29"
