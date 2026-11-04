"""校招实习的门店过滤先于截断，保留真实专业岗位反例并允许主动包含。"""

import json
from contextlib import closing

import pytest

from helpers import T, make_job
from jobradar import cli
from jobradar.core import queries as q
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import connect

FRONTLINE = ["门店运营学生用工", "门店兼职", "门店实习生(无锡万象城店)", "星级咖啡师（学生兼职）",
             "门店储备干部", "店长", "店员", "置业顾问", "房产经纪人", "洋北旗舰店诚聘合作伙伴(J45817)"]
PROFESSIONAL = ["搜推导购产品实习生", "门店产品经理", "闪购-导购Agent产品经理", "天猫运营专员/天猫店长",
    "Keeta技术-商城导购Java工程师", "算法工程师-AI导购大模型应用方向（T-Star Lab日常实习）",
    "人力资源业务合作伙伴-HRBP(J21270)", "门店财务实习生", "经纪人力负责人（广州）(J29135)"]


@pytest.mark.parametrize("title", FRONTLINE)
@pytest.mark.parametrize("kind", ["campus", "intern"])
def test_explicit_frontline_titles_are_hidden_only_by_default_and_remain_in_history(jobs_db, title, kind):
    job = make_job(1, title=title, recruit_type=kind)
    ingest_run(jobs_db, "s1", [job], ts=T(1))
    before = [tuple(r) for r in jobs_db.execute("SELECT * FROM job_event")]
    meta = {}
    assert q.search_jobs(jobs_db, recruit_type=kind, meta=meta) == []
    assert meta["frontline_filter"]["excluded_records"] == 1
    assert any("include-frontline" in hint for hint in meta["hints"])
    assert q.search_jobs(jobs_db, recruit_type=kind, include_frontline=True)
    assert q.get_job(jobs_db, None, job.id)
    assert [tuple(r) for r in jobs_db.execute("SELECT * FROM job_event")] == before


@pytest.mark.parametrize("title", PROFESSIONAL)
def test_actual_professional_counterexamples_survive_automatic_and_explicit_filters(jobs_db, title):
    ingest_run(jobs_db, "s1", [make_job(1, title=title, recruit_type="intern")], ts=T(1))
    assert q.search_jobs(jobs_db, recruit_type="intern")
    assert q.search_jobs(jobs_db, exclude_store=True)


def test_filtering_and_counts_happen_before_limit_without_changing_social_defaults(jobs_db):
    jobs = [make_job(1, title="店员"), make_job(2, title="店员"), make_job(3, title="软件工程师")]
    ingest_run(jobs_db, "s1", jobs, ts=T(1))
    meta = {}
    assert q.search_jobs(jobs_db, recruit_type="campus", limit=1, meta=meta)[0]["title"] == "软件工程师"
    assert meta["total"] == 1 and meta["frontline_filter"]["excluded_records"] == 2
    assert len(q.search_jobs(jobs_db)) == 3
    ingest_run(jobs_db, "social", [make_job(1, source_id="social", recruit_type="social", title="店员")], ts=T(1))
    assert q.search_jobs(jobs_db, recruit_type="social")
    assert not q.search_jobs(jobs_db, recruit_type="social", exclude_store=True)


def test_category_exclusion_uses_the_same_alias_union_and_keeps_unknowns(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, category="职能", subcategory="财务审计"),
        make_job(2, category="财务", subcategory=None), make_job(3, category=None, subcategory=None),
        make_job(4, category="职能", subcategory="行政")], ts=T(1))
    meta = {}
    rows = q.search_jobs(jobs_db, exclude_categories=["财务"], meta=meta)
    assert {r["id"] for r in rows} == {"s1:3", "s1:4"}
    assert "财务审计" in meta["excluded_category_matches"]["财务"]["matched"]
    assert any("职类缺失" in hint for hint in meta["hints"])


@pytest.mark.parametrize("kwargs", [{"exclude_categories":["不存在职类"]}, {"exclude_categories":"技术"},
    {"include_frontline":True,"exclude_store":True}, {"include_frontline":"yes"}, {"exclude_store":1}])
def test_invalid_or_conflicting_filters_do_not_silently_change_query_scope(jobs_db, kwargs):
    with pytest.raises(ValueError):
        q.search_jobs(jobs_db, **kwargs)


def test_text_filter_does_not_invent_a_removed_record_count(jobs_db, text_db):
    rows = [make_job(1, title="店员", requirements="PyTorch"),
            make_job(2, title="软件工程师", requirements="PyTorch")]
    ingest_run(jobs_db,"s1",rows,ts=T(1))
    upsert_texts(text_db,rows,ts=T(1))
    meta = {}
    assert len(q.search_jobs(jobs_db,recruit_type="campus",text="PyTorch",text_conn=text_db,meta=meta)) == 1
    assert meta["frontline_filter"]["excluded_records"] is None
    assert meta["frontline_filter"]["scope"] == "not_counted_for_fulltext"


@pytest.mark.parametrize("entry", ["cli", "mcp"])
def test_users_can_explicitly_request_frontline_jobs_through_both_entry_points(tmp_path, monkeypatch, capsys, entry):
    monkeypatch.setenv("JOBRADAR_HOME",str(tmp_path))
    with closing(connect(tmp_path/"jobs.db","jobs")) as jobs:
        ingest_run(jobs,"s1",[make_job(1,title="星级咖啡师",recruit_type="intern")],ts=T(1))
    if entry == "cli":
        cli.main(["search","--type","intern","--include-frontline"])
        result = json.loads(capsys.readouterr().out)
    else:
        mcp = pytest.importorskip("jobradar.mcp_server")
        result = mcp.search_jobs(recruit_type="intern",include_frontline=True)
    assert result["total"] == 1 and result["frontline_filter"]["mode"] == "include"


@pytest.mark.parametrize("entry", ["cli", "mcp"])
@pytest.mark.parametrize("command", ["search", "compare"])
def test_include_and_category_exclusion_are_shared_by_search_and_comparison(tmp_path, monkeypatch, capsys, entry, command):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    rows = [make_job(1, title="咖啡师实习生", recruit_type="intern"),
            make_job(2, title="财务实习生", recruit_type="intern", category="职能", subcategory="财务审计"),
            make_job(3, title="软件开发实习生", recruit_type="intern")]
    with closing(connect(tmp_path/"jobs.db","jobs")) as jobs, closing(connect(tmp_path/"jd_text.db","text")) as text:
        ingest_run(jobs,"s1",rows,ts=T(1))
        upsert_texts(text,rows,ts=T(1))
    if entry == "cli":
        cli.main([command, *(["腾讯"] if command == "compare" else []), "--type", "intern",
                  "--keyword", "实习", "--include-frontline", "--exclude-category", "财务"])
        result = json.loads(capsys.readouterr().out)
    else:
        mcp = pytest.importorskip("jobradar.mcp_server")
        kwargs = dict(recruit_type="intern", keyword="实习", include_frontline=True, exclude_categories=["财务"])
        result = mcp.search_jobs(**kwargs) if command == "search" else mcp.compare_roles(["腾讯"], **kwargs)
    jobs = result["results"] if command == "search" else result["results"]["腾讯"]
    assert {row["title"] for row in jobs} == {"咖啡师实习生", "软件开发实习生"}
