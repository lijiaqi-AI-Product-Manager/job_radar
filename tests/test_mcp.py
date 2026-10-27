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
    # 字段覆盖率要一起返回：agent 需要知道城市/届次能不能用
    assert set(st["jobs"]["fields"]) >= {"cities", "grad_year", "category", "campus_cities"}


def _manual_entry(**kw):
    from jobradar.pipeline.calendar import ManualEntry
    base = dict(
        id="t1-xz", group="腾讯", company="腾讯", grad_year=2027, project_type="秋招正式批",
        tracks=[{"direction": "技术类", "roles": ["后端"]}], apply_start="2026-08-03",
        apply_end="2026-11-30", cities=["北京", "深圳"], apply_url="https://careers.tencent.com/",
        source={"type": "official_site", "name": "官方招聘站", "url": "https://careers.tencent.com/",
                "date": "2026-08-03"},
        as_of="2026-10-26", jd={"status": "official_page", "url": "https://careers.tencent.com/"},
    )
    base.update(kw)
    return ManualEntry(**base)


@pytest.fixture
def cal_home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    from jobradar.pipeline import calendar as cal
    conn = connect(tmp_path / "calendar.db", "calendar")
    jobs = connect(tmp_path / "jobs.db", "jobs")
    cal.build(conn, jobs, manual=[_manual_entry()], sources=[],
              targets={"sectors": {"x": ["腾讯"]}}, ts=now_ts())
    conn.close()
    jobs.close()
    return tmp_path


def test_calendar_tool_filters_by_city_and_direction(cal_home):
    """MCP 的 calendar 工具必须能用城市/方向/截止日筛——这是用户最常问的三类问题。
    查询层早就支持了，但工具签名没暴露，等于 AI 助手永远用不到。"""
    assert mcp_server.calendar(city="北京")["results"][0]["id"] == "t1-xz"
    assert mcp_server.calendar(city="北京市")["results"], "带「市」也要能命中"
    assert mcp_server.calendar(city="拉萨")["results"] == []
    assert mcp_server.calendar(direction="技术类")["results"][0]["id"] == "t1-xz"
    assert mcp_server.calendar(direction="财务类")["results"] == []
    assert mcp_server.calendar(deadline_before="2026-12-31")["results"]
    assert mcp_server.calendar(deadline_before="2026-09-01")["results"] == []
    assert mcp_server.calendar(deadline_after="2026-11-01")["results"]
    assert mcp_server.calendar(has_window=True)["results"]
    assert mcp_server.calendar(has_tracks=True)["results"]


def test_calendar_tool_empty_city_says_why(cal_home):
    """按城市筛空了要给出 advice：只有部分条目写了城市，空≠没有岗位。
    不说清楚的话，用户会以为「拉萨真的没有校招」而放弃。"""
    out = mcp_server.calendar(city="拉萨")
    assert out["results"] == []
    assert out.get("advice") and "拉萨" in out["advice"]
