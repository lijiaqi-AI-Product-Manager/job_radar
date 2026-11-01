import pytest

from helpers import T, make_job
from jobradar.core import queries as q
from jobradar.pipeline import calendar as cal
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect


@pytest.mark.parametrize("kwargs", [{"limit": -1}, {"limit": 0}, {"company": " "},
                                    {"deadline_before": "2026-02-30"}, {"deadline_after": "tomorrow"}])
def test_invalid_search_parameters_are_rejected(jobs_db, kwargs):
    with pytest.raises(ValueError):
        q.search_jobs(jobs_db, **kwargs)


def test_nonpositive_trend_step_rejected_before_iteration(jobs_db, monkeypatch):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    def do_not_iterate(**kwargs):
        raise AssertionError("unsafe trend loop entered")
    monkeypatch.setattr(q, "timedelta", do_not_iterate)
    with pytest.raises(ValueError):
        q.company_trend(jobs_db, "腾讯", until="2026-11-01T00:00:00Z", step_days=0)


def test_empty_compare_company_rejected(jobs_db, text_db):
    with pytest.raises(ValueError):
        q.compare_roles(jobs_db, text_db, [""], category="算法")


def test_search_total_and_empty_reason_keep_company_scope(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(i, cities=["北京"]) for i in range(3)], ts=T(1))
    meta = {}
    assert len(q.search_jobs(jobs_db, company="腾讯", limit=1, meta=meta)) == 1
    assert meta["total"] == 3 and meta["returned"] == 1 and meta["truncated"] is True
    assert q.search_jobs(jobs_db, company="腾讯", city="拉萨", meta=meta) == []
    assert meta["empty_reason"] == "no_matching_jobs"
    assert meta["company_coverage"]["recorded_jobs"] == 3


def test_stats_and_trend_use_same_expiry_as_search(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-10-31"), make_job(2)], ts=T(1))
    assert q.data_summary(jobs_db)["open_jobs"] == len(q.search_jobs(jobs_db)) == 1
    assert q.company_trend(jobs_db, "腾讯", until="2026-11-01T00:00:00Z")[-1]["open"] == 1


def test_compare_preserves_city_type_and_graduation_filters(jobs_db, text_db):
    ingest_run(jobs_db, "s1", [make_job(1, cities=["北京"]), make_job(2, cities=["深圳"])], ts=T(1))
    rows = q.compare_roles(jobs_db, text_db, ["腾讯"], category="技术", city="深圳",
                           recruit_type="campus", grad_year=2027)
    assert [r["id"] for r in rows["腾讯"]] == ["s1:2"]


def test_calendar_advice_never_counts_other_company(tmp_path, jobs_db):
    conn = connect(tmp_path / "cal.db", "calendar")
    entries = [cal.ManualEntry(id=slug, group=name, project_type="校招", cities=[city],
                               as_of="2026-11-01", source={"type": "official_site", "name": "公开公告"})
               for slug, name, city in (("jd", "京东", "上海"), ("qq", "腾讯", "北京"))]
    cal.build(conn, jobs_db, manual=entries, sources=[], targets={"sectors": {}}, ts=T(1))
    advice = q.calendar_filter_advice(conn, group="京东", city="北京")
    assert "命中 1 条" not in advice
    assert "0" in advice or "没有" in advice
    conn.close()


def test_cec_company_query_does_not_return_cetc_jobs(jobs_db):
    ingest_run(jobs_db, "cetc36", [make_job(1, source_id="cetc36",
               company="中国电子科技集团公司第三十六研究所0607")], ts=T(1))
    assert q.search_jobs(jobs_db, company="中国电子") == []
