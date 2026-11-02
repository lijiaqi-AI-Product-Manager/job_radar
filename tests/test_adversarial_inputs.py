"""从使用者输入与结果含义独立断言，不复用查询实现构造预期结果。"""

import json

import pytest

from helpers import T, make_job
from jobradar import cli
from jobradar.core import queries as q
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect


@pytest.mark.parametrize("literal", ["%", "_", "\\"])
def test_title_keyword_is_a_literal_substring(jobs_db, literal):
    ingest_run(
        jobs_db,
        "s1",
        [make_job(1, title="普通工程师"), make_job(2, title=f"包含{literal}的岗位")],
        ts=T(1),
    )
    assert [r["id"] for r in q.search_jobs(jobs_db, keyword=literal)] == ["s1:2"]


@pytest.mark.parametrize("field", ["group", "company", "project_type", "direction"])
@pytest.mark.parametrize("literal", ["%", "_"])
def test_calendar_filters_do_not_treat_user_text_as_sql_wildcards(field, literal):
    from jobradar.pipeline import calendar as cal

    with connect(":memory:", "jobs") as jobs, connect(":memory:", "calendar") as calendar:
        row = cal.ManualEntry(
            id="sample",
            group="示例公司",
            project_type="校招",
            tracks=[{"direction": "技术类", "roles": []}],
            as_of="2026-11-01",
            source={"type": "official_site", "name": "公开招聘站", "url": "https://example.test"},
        )
        cal.build(calendar, jobs, manual=[row], sources=[], targets={"sectors": {}}, ts=T(1))
        assert q.calendar_entries(calendar, **{field: literal}) == []


def test_calendar_city_suffix_is_symmetric():
    from jobradar.pipeline import calendar as cal

    with connect(":memory:", "jobs") as jobs, connect(":memory:", "calendar") as calendar:
        row = cal.ManualEntry(
            id="sample",
            group="示例公司",
            project_type="校招",
            cities=["深圳市"],
            as_of="2026-11-01",
            source={"type": "official_site", "name": "公开招聘站", "url": "https://example.test"},
        )
        cal.build(calendar, jobs, manual=[row], sources=[], targets={"sectors": {}}, ts=T(1))
        assert [r["id"] for r in q.calendar_entries(calendar, city="深圳")] == ["sample"]
        assert [r["id"] for r in q.calendar_entries(calendar, city="深圳市")] == ["sample"]


def test_oversized_limit_is_a_validation_error(jobs_db):
    with pytest.raises(ValueError, match="limit"):
        q.search_jobs(jobs_db, limit=10**100)


def test_compare_rejects_a_string_in_place_of_company_list(jobs_db, text_db):
    with pytest.raises(ValueError, match="公司"):
        q.compare_roles(jobs_db, text_db, "腾讯", category="技术")


def test_human_table_preserves_staleness_truncation_and_empty_hints(capsys):
    import argparse

    payload = {
        "data_as_of": "2026-10-20",
        "stale": True,
        "total": 30,
        "truncated": True,
        "results": [],
        "hints": ["去掉城市条件再查一次"],
    }
    cli._emit(argparse.Namespace(table=True), payload)
    out = capsys.readouterr().out
    assert "陈旧" in out
    assert "截断" in out
    assert "去掉城市条件再查一次" in out
    assert json.dumps(payload, ensure_ascii=False) != out
