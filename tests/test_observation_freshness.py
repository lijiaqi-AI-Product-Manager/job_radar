"""来源成功刷新，不等于每个历史岗位都再次被观测到。"""

import json

import pytest

from helpers import T, make_job
from jobradar import cli, local
from jobradar.core import queries as q
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect


@pytest.mark.parametrize("entry", ["search", "detail", "compare"])
def test_missing_from_latest_success_is_visible_but_not_confirmed(jobs_db, text_db, monkeypatch, entry):
    monkeypatch.setattr(q, "now_ts", lambda: T(5))
    monkeypatch.setattr(local, "now_ts", lambda: T(5))
    a, b = make_job(1), make_job(2)
    ingest_run(jobs_db, "s1", [a, b], ts=T(1))
    assert ingest_run(jobs_db, "s1", [b], ts=T(4)).status == "ok"
    before = [tuple(r) for r in jobs_db.execute("SELECT * FROM job")]
    events = [tuple(r) for r in jobs_db.execute("SELECT * FROM job_event")]
    if entry == "search":
        row = next(r for r in q.search_jobs(jobs_db) if r["id"] == a.id)
    elif entry == "detail":
        row = q.get_job(jobs_db, text_db, a.id)
    else:
        row = next(r for r in q.compare_roles(jobs_db, text_db, ["腾讯"], category="技术")["腾讯"] if r["id"] == a.id)
    assert row["availability"] == "unconfirmed_not_seen"
    assert row["not_seen_in_latest_success"] is True
    assert row["source_stale"] is False and row["job_stale"] is True
    assert row["job_age_hours"] == 96
    assert "未再次" in row["availability_label"]
    assert any("不能据此确认" in text for text in row["source_warnings"])
    assert local.envelope(jobs_db, [row])["stale"] is True
    assert local.envelope(jobs_db, [row])["snapshot_stale"] is False
    assert local.envelope(jobs_db, [row])["availability_counts"] == {"unconfirmed_not_seen": 1}
    assert [tuple(r) for r in jobs_db.execute("SELECT * FROM job")] == before
    assert [tuple(r) for r in jobs_db.execute("SELECT * FROM job_event")] == events


def test_recent_missing_candidate_is_unconfirmed_without_claiming_48h_old(jobs_db, monkeypatch):
    monkeypatch.setattr(q, "now_ts", lambda: T(2, 12))
    monkeypatch.setattr(local, "now_ts", lambda: T(2, 12))
    a, b = make_job(1), make_job(2)
    ingest_run(jobs_db, "s1", [a, b], ts=T(1))
    ingest_run(jobs_db, "s1", [b], ts=T(2))
    row = q.get_job(jobs_db, None, a.id)
    assert row["availability"] == "unconfirmed_not_seen"
    assert row["job_stale"] is False and row["job_age_hours"] == 36
    assert local.envelope(jobs_db, [row])["stale"] is False


def test_observed_only_uses_last_complete_observation_before_count_and_limit(tmp_path, monkeypatch, capsys):
    from jobradar import source_catalog

    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    monkeypatch.setattr(q, "now_ts", lambda: T(5))
    monkeypatch.setattr(source_catalog, "catalog", lambda: {
        sid: {"enabled": sid != "paused"} for sid in ("s1", "edge", "old", "paused", "future")})
    with connect(tmp_path / "jobs.db", "jobs") as conn:
        seen, missing, expired = make_job(1), make_job(2), make_job(3, apply_end="2026-10-04")
        ingest_run(conn, "s1", [seen, missing, expired], ts=T(1))
        ingest_run(conn, "s1", [seen, expired], ts=T(4))
        ingest_run(conn, "s1", [], ts=T(5), ok=False, error="ReadTimeout")
        for sid, ts in (("edge", T(3)), ("old", T(2, 23)), ("paused", T(4)),
                        ("unknown", T(4)), ("future", T(6))):
            ingest_run(conn, sid, [make_job(4, source_id=sid)], ts=ts)
        previous = conn.total_changes
        meta = {}
        rows = q.search_jobs(conn, observed_only=True, meta=meta)
        assert {r["source_id"] for r in rows} == {"s1", "edge"}
        assert all(r["availability"] == "observed_recently" for r in rows)
        assert seen.id in {r["id"] for r in rows} and meta["total"] == 2
        assert len(q.search_jobs(conn, observed_only=True, limit=1, meta=meta)) == 1 and meta["total"] == 2
        assert any("48小时" in hint for hint in meta["hints"])
        assert conn.total_changes == previous
        with pytest.raises(ValueError, match="include_closed"):
            q.search_jobs(conn, observed_only=True, include_closed=True)
    cli.main(["search", "--observed-only", "--limit", "1"])
    cli_payload = json.loads(capsys.readouterr().out)
    mcp = pytest.importorskip("jobradar.mcp_server")
    mcp_payload = mcp.search_jobs(observed_only=True, dedupe=False, limit=1)
    assert [r["id"] for r in cli_payload["results"]] == [r["id"] for r in mcp_payload["results"]]
    assert cli_payload["total"] == mcp_payload["total"] == 2


def test_failed_or_rejected_run_does_not_claim_a_job_disappeared(jobs_db, monkeypatch):
    monkeypatch.setattr(q, "now_ts", lambda: T(2))
    job = make_job(1)
    ingest_run(jobs_db, "s1", [job], ts=T(1))
    ingest_run(jobs_db, "s1", [], ts=T(2), ok=False, error="ReadTimeout")
    assert ingest_run(jobs_db, "s1", [], ts=T(2)).status == "rejected"
    row = q.get_job(jobs_db, None, job.id)
    assert row["not_seen_in_latest_success"] is False
    assert row["availability"] == "observed_recently"


def test_reobserved_job_recovers_its_current_observation_status(jobs_db, monkeypatch):
    monkeypatch.setattr(q, "now_ts", lambda: T(4))
    a, b = make_job(1), make_job(2)
    ingest_run(jobs_db, "s1", [a, b], ts=T(1))
    ingest_run(jobs_db, "s1", [b], ts=T(2))
    ingest_run(jobs_db, "s1", [a, b], ts=T(3))
    row = q.get_job(jobs_db, None, a.id)
    assert row["availability"] == "observed_recently"
    assert row["not_seen_in_latest_success"] is row["job_stale"] is False


def test_folded_group_prefers_the_record_actually_seen_in_latest_crawl(jobs_db, monkeypatch):
    monkeypatch.setattr(q, "now_ts", lambda: T(4))
    a, b = make_job(1, title="软件工程师"), make_job(2, title="软件工程师")
    ingest_run(jobs_db, "s1", [a, b], ts=T(1))
    ingest_run(jobs_db, "s1", [b], ts=T(3))
    meta = {}
    row, = q.search_jobs(jobs_db, dedupe=True, meta=meta)
    assert row["id"] == b.id and row["availability"] == "observed_recently"
    assert row["variants"] == 2 and meta["total"] == 1


def test_blank_tool_query_is_an_error_and_next_request_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    connect(tmp_path / "jd_text.db", "text").close()
    with connect(tmp_path / "jobs.db", "jobs") as conn:
        ingest_run(conn, "s1", [make_job(1)], ts=T(1))
    mcp = pytest.importorskip("jobradar.mcp_server")
    import asyncio
    result = asyncio.run(mcp.server.call_tool("search_jobs", {"text": "  "}))
    assert result.is_error and "非空" in result.structured_content["error"]
    assert mcp.search_jobs(company="腾讯")["results"]


def test_table_explains_candidate_missing_from_latest_success(capsys):
    from argparse import Namespace
    cli._emit(Namespace(table=True), {"results": [{"title": "研发工程师", "company": "示例",
        "not_seen_in_latest_success": True, "availability_label": "历史记录，最新采集中未再次见到"}]})
    output = capsys.readouterr().out
    assert "未再次出现" in output and "不代表已下架" in output


def test_recent_snapshot_with_old_candidate_does_not_request_repeated_download(capsys):
    from argparse import Namespace
    cli._emit(Namespace(table=True), {"stale": True, "snapshot_stale": False,
        "results": [{"title": "研发工程师", "company": "示例", "job_stale": True}]})
    output = capsys.readouterr().out
    assert "快照较新" in output and "原始链接" in output
    assert "可先运行 jobradar update" not in output


def test_old_global_snapshot_still_requests_update(jobs_db, monkeypatch):
    monkeypatch.setattr(local, "now_ts", lambda: T(5))
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    result = local.envelope(jobs_db, [])
    assert result["snapshot_stale"] is result["stale"] is True


@pytest.mark.parametrize("kind", ["search", "detail"])
def test_cli_and_mcp_expose_the_same_missing_observation(tmp_path, monkeypatch, capsys, kind):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    monkeypatch.setattr(q, "now_ts", lambda: T(4))
    monkeypatch.setattr(local, "now_ts", lambda: T(4))
    with connect(tmp_path / "jobs.db", "jobs") as conn:
        a, b = make_job(1), make_job(2)
        ingest_run(conn, "s1", [a, b], ts=T(1))
        ingest_run(conn, "s1", [b], ts=T(3))
    cli.main(["search"] if kind == "search" else ["show", a.id])
    payload = json.loads(capsys.readouterr().out)
    mcp = pytest.importorskip("jobradar.mcp_server")
    other = mcp.search_jobs(dedupe=False) if kind == "search" else mcp.get_job(a.id)
    for result in (payload, other):
        row = next(r for r in result["results"] if r["id"] == a.id)
        assert row["availability"] == "unconfirmed_not_seen"
        assert result["availability_counts"]["unconfirmed_not_seen"] == 1


@pytest.mark.parametrize("selector", ["text", "keyword"])
@pytest.mark.parametrize("value", ["", " \t\n ", 42])
def test_blank_or_invalid_search_text_does_not_silently_broaden(jobs_db, selector, value):
    with pytest.raises(ValueError):
        q.search_jobs(jobs_db, **{selector: value})
