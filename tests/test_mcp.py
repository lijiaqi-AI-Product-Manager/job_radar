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
    jobs.close()
    text.close()
    return tmp_path


def test_tools_return_envelopes(home):
    assert mcp_server.search_jobs(company="腾讯")["results"][0]["id"] == "s1:1"
    assert mcp_server.get_job("s1:1")["results"][0]["requirements"] == "PyTorch"
    assert mcp_server.recent_changes(days=1)["results"][0]["type"] == "open"
    assert mcp_server.new_jobs_by_category(days=1)["results"] == [{"category": "技术", "n": 1}]
    assert mcp_server.compare_roles(["腾讯", "无"], "算法")["not_found"] == ["无"]
    assert mcp_server.company_trend("腾讯")["results"]
    assert mcp_server.data_status()["failing"] == []


def test_missing_data_is_an_error_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    out = mcp_server.search_jobs()
    assert "jobradar update" in out["error"] and out["results"] == []


def test_search_full_text(home):
    out = mcp_server.search_jobs(text="pytorch")
    assert out["results"][0]["id"] == "s1:1" and out["results"][0]["match"] == "PyTorch"
    (home / "jd_text.db").unlink()
    assert "error" in mcp_server.search_jobs(text="pytorch")


def test_calendar_and_stats_tools(home):
    from jobradar.pipeline import calendar as cal
    conn = connect(home / "calendar.db", "calendar")
    jobs = connect(home / "jobs.db", "jobs")
    cal.build(conn, jobs, manual=[], sources=[], targets={"sectors": {"x": ["腾讯", "阿里巴巴"]}}, ts=now_ts())
    conn.close()
    out = mcp_server.calendar(group="腾讯")
    assert out["results"] and out["results"][0]["origin"] == "auto"
    st = mcp_server.stats()
    assert st["calendar"]["calendar_covered"] == 1 and st["calendar"]["missing_calendar"] == ["阿里巴巴"]
