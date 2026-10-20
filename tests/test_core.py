"""查询层：agent 看到的所有答案都从这里出来。错了就是"看似权威的胡说"，所以测试要细。"""

import pytest

from helpers import T, make_job
from jobradar.core.queries import (
    company_trend,
    compare_roles,
    data_as_of,
    data_status,
    get_job,
    recent_changes,
    search_jobs,
)
from jobradar.pipeline.ingest import ingest_run, upsert_texts


def s1_jobs(**first):
    return [
        make_job(1, title="后端开发工程师", category="技术", subcategory="后端", cities=["深圳"], **first),
        make_job(2, title="算法工程师（大模型）", category="技术", subcategory="算法", cities=["北京", "深圳"]),
        make_job(3, title="产品经理", category="产品", subcategory=None, cities=["上海"], recruit_type="intern", grad_year=2028),
    ]


@pytest.fixture
def seeded(jobs_db):
    ingest_run(jobs_db, "s1", s1_jobs(), ts=T(1))
    ingest_run(jobs_db, "s2", [
        make_job(1, source_id="s2", company="阿里巴巴", title="算法工程师", subcategory="算法", cities=["杭州"]),
    ], ts=T(2))
    return jobs_db


def titles(rows):
    return [r["title"] for r in rows]


def test_search_no_filter_returns_all_open(seeded):
    assert len(search_jobs(seeded)) == 4


def test_search_by_company_is_substring(seeded):
    assert len(search_jobs(seeded, company="腾讯")) == 3
    assert len(search_jobs(seeded, company="阿里")) == 1


def test_search_by_category_matches_category_or_subcategory(seeded):
    assert len(search_jobs(seeded, category="技术")) == 3
    assert titles(search_jobs(seeded, category="算法", company="腾讯")) == ["算法工程师（大模型）"]


def test_search_by_city_uses_exact_element(seeded):
    assert len(search_jobs(seeded, city="深圳")) == 2
    assert search_jobs(seeded, city="深") == []


def test_search_by_recruit_type_and_grad_year(seeded):
    assert titles(search_jobs(seeded, recruit_type="intern")) == ["产品经理"]
    assert titles(search_jobs(seeded, grad_year=2028)) == ["产品经理"]


def test_search_keyword_matches_title(seeded):
    assert len(search_jobs(seeded, keyword="算法")) == 2


def test_search_hides_closed_by_default(seeded):
    for d in (3, 4, 5):
        ingest_run(seeded, "s1", s1_jobs()[1:], ts=T(d))  # 岗位 1 连续缺席
    assert "后端开发工程师" not in titles(search_jobs(seeded))
    assert "后端开发工程师" in titles(search_jobs(seeded, include_closed=True))


def test_search_result_shape_has_source_and_dates(seeded):
    r = search_jobs(seeded, company="阿里")[0]
    assert r["company"] == "阿里巴巴"
    assert r["url"].startswith("http")
    assert r["cities"] == ["杭州"]
    assert {"id", "first_seen", "last_seen", "closed_at", "recruit_type", "grad_year", "batch"} <= set(r)


def test_search_limit_and_newest_first(seeded):
    rows = search_jobs(seeded, limit=2)
    assert len(rows) == 2
    assert rows[0]["first_seen"] >= rows[1]["first_seen"]


def test_recent_changes_filters_by_time_company_and_type(seeded):
    ingest_run(seeded, "s1", s1_jobs(department="新部门"), ts=T(6))
    ev = recent_changes(seeded, since=T(5))
    assert [(e["type"], e["job_id"]) for e in ev] == [("change", "s1:1")]
    assert len(recent_changes(seeded, since=T(1))) == 5  # 4 open + 1 change
    assert all(e["company"] == "阿里巴巴" for e in recent_changes(seeded, since=T(1), company="阿里"))
    assert {e["type"] for e in recent_changes(seeded, since=T(1), types=["open"])} == {"open"}


def test_recent_changes_newest_first_and_has_link(seeded):
    ev = recent_changes(seeded, since=T(1))
    assert [e["ts"] for e in ev] == sorted((e["ts"] for e in ev), reverse=True)
    assert ev[0]["url"].startswith("http") and ev[0]["title"]


def test_company_trend(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2)], ts=T(3))
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2), make_job(3)], ts=T(8))
    for d in (9, 10, 11):
        ingest_run(jobs_db, "s1", [make_job(2), make_job(3)], ts=T(d))  # 岗位 1 于 10-11 关闭
    trend = company_trend(jobs_db, "腾讯", until=T(15), step_days=7)
    assert [(p["date"], p["open"]) for p in trend] == [
        ("2026-10-01", 1), ("2026-10-08", 3), ("2026-10-15", 2),
    ]


def test_company_trend_unknown_company_is_empty(jobs_db):
    assert company_trend(jobs_db, "不存在", until=T(15)) == []


def test_data_status(jobs_db):
    ingest_run(jobs_db, "ok_fresh", [make_job(1, source_id="ok_fresh")], ts=T(10, 12))
    ingest_run(jobs_db, "old", [make_job(1, source_id="old")], ts=T(5))
    ingest_run(jobs_db, "never_ok", [], ts=T(10), ok=False, error="boom")
    ingest_run(jobs_db, "now_failing", [make_job(1, source_id="now_failing")], ts=T(10, 6))
    ingest_run(jobs_db, "now_failing", [], ts=T(11, 6), ok=False, error="boom")

    st = {s["source_id"]: s for s in data_status(jobs_db, now=T(11, 12))}
    assert st["ok_fresh"]["stale"] is False and st["ok_fresh"]["age_hours"] == 24
    assert st["old"]["stale"] is True
    assert st["never_ok"]["last_ok"] is None and st["never_ok"]["stale"] is True
    assert st["now_failing"]["last_status"] == "failed" and st["now_failing"]["last_ok"] == T(10, 6)
    assert st["ok_fresh"]["open_jobs"] == 1


def test_compare_roles(jobs_db, text_db):
    a = [make_job(1, company="腾讯", subcategory="算法", requirements="精通 PyTorch"),
         make_job(2, company="腾讯", subcategory="算法", requirements="熟悉 CUDA"),
         make_job(3, company="腾讯", subcategory="后端", requirements="Go")]
    b = [make_job(1, source_id="s2", company="字节跳动", subcategory="算法")]  # 无 JD 文本
    ingest_run(jobs_db, "s1", a, ts=T(1))
    ingest_run(jobs_db, "s2", b, ts=T(1))
    upsert_texts(text_db, a, ts=T(1))

    out = compare_roles(jobs_db, text_db, ["腾讯", "字节跳动", "不存在公司"], "算法", per_company=1)
    assert len(out["腾讯"]) == 1 and out["腾讯"][0]["requirements"] in {"精通 PyTorch", "熟悉 CUDA"}
    assert out["字节跳动"][0]["requirements"] is None
    assert out["不存在公司"] == []  # 空列表 = 库里没有，skill 据此回答"没有数据"


def test_get_job_with_text_and_unknown(jobs_db, text_db):
    j = make_job(1, requirements="熟悉 Go")
    ingest_run(jobs_db, "s1", [j], ts=T(1))
    upsert_texts(text_db, [j], ts=T(1))
    got = get_job(jobs_db, text_db, "s1:1")
    assert got["title"] == j.title and got["requirements"] == "熟悉 Go" and got["url"].startswith("http")
    assert get_job(jobs_db, None, "s1:1")["requirements"] is None  # 未下载 JD 库也能用
    assert get_job(jobs_db, text_db, "nope") is None


def test_data_as_of_is_latest_successful_run(jobs_db):
    assert data_as_of(jobs_db) is None
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(3))
    ingest_run(jobs_db, "s1", [], ts=T(4), ok=False, error="x")
    assert data_as_of(jobs_db) == T(3)
