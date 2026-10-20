import pytest

from helpers import make_job
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts

mcp_server = pytest.importorskip("jobradar.mcp_server")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    jobs = connect(tmp_path / "jobs.db", "jobs")
    text = connect(tmp_path / "jd_text.db", "text")
    j = make_job(1, subcategory="算法", requirements="PyTorch")
    ingest_run(jobs, "s1", [j], ts=now_ts())
    upsert_texts(text, [j], ts=now_ts())
    return tmp_path


def test_tools_return_envelopes(home):
    assert mcp_server.search_jobs(company="腾讯")["results"][0]["id"] == "s1:1"
    assert mcp_server.get_job("s1:1")["results"][0]["requirements"] == "PyTorch"
    assert mcp_server.recent_changes(days=1)["results"][0]["type"] == "open"
    assert mcp_server.compare_roles(["腾讯", "无"], "算法")["not_found"] == ["无"]
    assert mcp_server.company_trend("腾讯")["results"]
    assert mcp_server.data_status()["failing"] == []


def test_missing_data_is_an_error_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    out = mcp_server.search_jobs()
    assert "jobradar update" in out["error"] and out["results"] == []
