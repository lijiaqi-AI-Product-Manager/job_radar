"""求职约束在截断前执行，缺失字段与冲突证据不能被当作资格结论。"""

import sqlite3

import pytest

from helpers import T, make_job
from jobradar.core import queries as q
from jobradar.pipeline.ingest import ingest_run, upsert_texts


def seed(jobs_db, text_db=None, **changes):
    rows = [make_job(1, title="财务会计", category="职能", subcategory="财务审计",
                     cities=["苏州"], grad_year=2027, apply_end="2026-11-09", **changes),
            make_job(2, cities=["无锡", "上海市"], grad_year=None),
            make_job(3, cities=["无锡市"], grad_year=None),
            make_job(4, cities=[], grad_year=2026)]
    ingest_run(jobs_db, "s1", rows, ts=T(1))
    if text_db:
        upsert_texts(text_db, rows, ts=T(1))
    return rows


@pytest.mark.parametrize("dedupe", [False, True])
def test_multiple_cities_and_exclusions_are_applied_before_limit_and_count(jobs_db, dedupe):
    seed(jobs_db)
    meta = {}
    rows = q.search_jobs(jobs_db, cities=["苏州市", "无锡"], exclude_cities=["上海"],
                         dedupe=dedupe, limit=1, meta=meta)
    assert [r["id"] for r in rows] == ["s1:1"]
    assert meta["total"] == 2 and meta["truncated"] is True
    assert [r["id"] for r in q.search_jobs(jobs_db, cities=["苏州", "无锡"],
                exclude_cities=["上海市"], limit=20)] == ["s1:1", "s1:3"]


def test_negative_city_does_not_pretend_missing_location_is_confirmed(jobs_db):
    seed(jobs_db)
    meta = {}
    rows = q.search_jobs(jobs_db, exclude_cities=["上海"], meta=meta)
    assert [r["id"] for r in rows] == ["s1:1", "s1:3", "s1:4"]
    assert any("城市缺失" in hint for hint in meta["hints"])


@pytest.mark.parametrize("term", ["%", "_", "\\"])
def test_excluded_titles_are_literal_substrings(jobs_db, term):
    ingest_run(jobs_db, "s1", [make_job(1, title=f"开发{term}岗"),
                              make_job(2, title="普通开发")], ts=T(1))
    assert [r["id"] for r in q.search_jobs(jobs_db, exclude_keywords=[term])] == ["s1:2"]


def test_excluded_company_alias_never_removes_another_entity(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, company="字节跳动")], ts=T(1))
    ingest_run(jobs_db, "s2", [make_job(1, source_id="s2", company="京东方")], ts=T(1))
    meta = {}
    assert [r["company"] for r in q.search_jobs(jobs_db, exclude_companies=["bytedance"], meta=meta)] == ["京东方"]
    assert meta["excluded_company_matches"]["bytedance"]["match"] == "alias"
    assert [r["company"] for r in q.search_jobs(jobs_db, exclude_companies=["京东"])] == ["字节跳动", "京东方"]


def test_ambiguous_excluded_company_requires_clarification(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, company="中国核工业集团")], ts=T(1))
    ingest_run(jobs_db, "s2", [make_job(1, source_id="s2", company="中国船舶集团")], ts=T(1))
    with pytest.raises(ValueError, match="排除公司"):
        q.search_jobs(jobs_db, exclude_companies=["中国"])


@pytest.mark.parametrize("kwargs", [
    {"cities": "上海"}, {"exclude_cities": [""]}, {"exclude_keywords": [None]},
    {"exclude_companies": ["  "]}, {"cities": ["上海"], "city": "北京"},
    {"include_unknown_grad_year": True}, {"exclude_keywords": ["x"] * 101},
])
def test_invalid_constraints_are_rejected_before_querying(jobs_db, kwargs):
    with pytest.raises(ValueError):
        q.search_jobs(jobs_db, **kwargs)


def test_nonempty_year_query_reports_the_missing_cohort_with_other_constraints(jobs_db):
    seed(jobs_db)
    meta = {}
    rows = q.search_jobs(jobs_db, cities=["苏州", "无锡"], grad_year=2027, meta=meta)
    assert [r["id"] for r in rows] == ["s1:1"]
    coverage = meta["filter_coverage"]["grad_year"]
    assert (coverage["total"], coverage["known"], coverage["unknown"]) == (3, 1, 2)
    assert coverage["unit"] == "records"
    assert any("届次" in h and "2" in h for h in meta["hints"])
    assert jobs_db.execute("SELECT grad_year FROM job WHERE id='s1:3'").fetchone()[0] is None


def test_optional_unknown_cohort_is_labeled_and_never_claimed_as_eligible(jobs_db):
    seed(jobs_db)
    rows = q.search_jobs(jobs_db, grad_year=2027, include_unknown_grad_year=True)
    assert {r["id"]: r["grad_year_match"] for r in rows} == {
        "s1:1": "explicit", "s1:2": "unknown", "s1:3": "unknown"}
    assert all(r["grad_year"] is None for r in rows if r["grad_year_match"] == "unknown")


def test_fulltext_coverage_does_not_invent_relaxed_counts(jobs_db, text_db):
    seed(jobs_db, text_db, description="Python")
    meta = {}
    rows = q.search_jobs(jobs_db, text="Python", text_conn=text_db, grad_year=2027, meta=meta)
    assert rows
    assert meta["filter_coverage"]["grad_year"]["unknown"] is None
    assert meta["filter_coverage"]["grad_year"]["scope"] == "not_counted_for_fulltext"
    assert any("届次" in h for h in meta["hints"])


def test_word_occurrence_is_not_silently_presented_as_qualification(jobs_db, text_db):
    job = make_job(1, requirements="不支持远程办公，每周五天到岗。")
    ingest_run(jobs_db, "s1", [job], ts=T(1))
    upsert_texts(text_db, [job], ts=T(1))
    meta = {}
    assert q.search_jobs(jobs_db, text="远程", text_conn=text_db, meta=meta)
    assert meta["text_match_semantics"] == "literal_terms"
    assert any("关键词命中不代表" in h for h in meta["hints"])


def test_deadline_filter_warns_about_unknown_dates_even_when_not_empty(jobs_db):
    seed(jobs_db)
    meta = {}
    assert q.search_jobs(jobs_db, deadline_before="2026-11-10", meta=meta)
    assert meta["filter_coverage"]["apply_end"]["unknown"] == 3
    assert any("截止日" in h for h in meta["hints"])


@pytest.mark.parametrize("term", ["财务", "会计", "财务审计"])
def test_finance_words_reach_the_specific_category_without_broadening_to_all_support(jobs_db, term):
    seed(jobs_db)
    ingest_run(jobs_db, "s2", [make_job(1, source_id="s2", title="行政专员",
                                      category="职能", subcategory="行政")], ts=T(1))
    meta = {}
    assert [r["id"] for r in q.search_jobs(jobs_db, category=term, meta=meta)] == ["s1:1"]
    assert meta["category_match"]["matched"] == ["财务审计", "会计", "审计", "财务"]


def test_unknown_category_explains_vocabulary_instead_of_blaming_missing_data(jobs_db):
    seed(jobs_db)
    meta = {}
    assert q.search_jobs(jobs_db, category="不存在的职类", meta=meta) == []
    assert meta["category_match"]["match"] == "none"
    assert "财务审计" in meta["category_match"]["available"]
    assert any("词表" in h for h in meta["hints"])


@pytest.mark.parametrize("term,target", [("ByteDance", "字节跳动"), ("ＢＹＴＥＤＡＮＣＥ", "字节跳动"),
                                       ("Microsoft", "微软"), ("microsoft", "微软")])
def test_english_company_alias_has_same_identity_as_chinese(jobs_db, term, target):
    ingest_run(jobs_db, "s1", [make_job(1, company=target)], ts=T(1))
    assert [r["company"] for r in q.search_jobs(jobs_db, company=term)] == [target]


@pytest.mark.parametrize("types", [["closed"], ["open", "typo"], "close", [], [1]])
def test_unknown_event_type_is_an_error_instead_of_an_empty_result(jobs_db, types):
    with pytest.raises(ValueError, match="types"):
        q.recent_changes(jobs_db, since=T(1), types=types)


def test_not_indexed_company_hint_is_distinct_from_ambiguity():
    hints = q.empty_result_hints([], company_match={"match": "none", "matched": []})
    assert "未收录" in hints[0] and "不唯一" not in hints[0] and "没有唯一确定" not in hints[0]


@pytest.mark.parametrize("different", [{"recruit_type": "intern"}, {"grad_year": 2026},
                                      {"degree_min": "硕士"}, {"apply_end": "2026-11-10"},
                                      {"department": "另一个部门"}, {"batch": "提前批"}])
def test_folding_does_not_erase_different_eligibility_or_windows(jobs_db, different):
    ingest_run(jobs_db, "s1", [make_job(1, title="软件工程师"),
                              make_job(2, title="软件工程师", **different)], ts=T(1))
    assert len(q.search_jobs(jobs_db, dedupe=True)) == 2


@pytest.mark.parametrize("entry", ["search", "detail", "compare"])
def test_degree_conflict_is_visible_without_overwriting_either_source(jobs_db, text_db, entry):
    job = make_job(1, degree_min="硕士", requirements="1、本科及以上学历，计算机等相关专业。")
    ingest_run(jobs_db, "s1", [job], ts=T(20))
    upsert_texts(text_db, [job], ts=T(1))
    before = tuple(jobs_db.execute("SELECT * FROM job").fetchone())
    if entry == "search":
        row = q.search_jobs(jobs_db, text_conn=text_db)[0]
    elif entry == "detail":
        row = q.get_job(jobs_db, text_db, job.id)
    else:
        row = q.compare_roles(jobs_db, text_db, ["腾讯"], category="技术")["腾讯"][0]
    evidence = row["qualification_evidence"]
    assert evidence["degree"]["structured"] == "硕士"
    assert evidence["degree"]["jd"] == "本科" and evidence["degree"]["conflict"] is True
    assert "本科及以上" in evidence["degree"]["excerpt"]
    assert evidence["text_observed_at"] == T(1)
    assert row["degree_min"] == "硕士" and row["field_warnings"]
    assert tuple(jobs_db.execute("SELECT * FROM job").fetchone()) == before


def test_social_channel_can_explicitly_accept_graduates_without_being_relabeled(jobs_db, text_db):
    job = make_job(1, recruit_type="social", grad_year=2027,
                   description="星系计划面向2027届毕业生及毕业两年内伙伴。")
    ingest_run(jobs_db, "s1", [job], ts=T(20))
    upsert_texts(text_db, [job], ts=T(1))
    row = q.get_job(jobs_db, text_db, job.id)
    assert row["recruit_type"] == "social" and row["grad_year"] == 2027
    assert any("渠道" in w and "资格" in w for w in row["field_warnings"])


def test_project_listing_is_not_presented_as_a_direct_job_link(jobs_db, monkeypatch):
    from jobradar import source_catalog

    monkeypatch.setattr(source_catalog, "catalog", lambda: {"s1": {"adapter": "netease", "enabled": True}})
    ingest_run(jobs_db, "s1", [make_job(1, url="https://campus.example.test/app/job/position?id=102")], ts=T(1))
    row = q.search_jobs(jobs_db)[0]
    assert row["url_scope"] == "project_listing" and "列表" in row["url_hint"]


@pytest.mark.parametrize("entry", ["search", "detail", "event"])
def test_recorded_cec_dead_route_gets_a_reviewed_public_listing_without_mutating_history(jobs_db, text_db, entry):
    old_url = "https://campus.cec.com.cn/position/835504585052092"
    job = make_job(1, source_id="jsonportal-cec", url=old_url)
    ingest_run(jobs_db, job.source_id, [job], ts=T(1))
    row = (q.search_jobs(jobs_db)[0] if entry == "search" else q.recent_changes(jobs_db, since=T(1))[0]
           if entry == "event" else q.get_job(jobs_db, text_db, job.id))
    assert row["recorded_url"] == old_url
    assert row["url"] == "https://campus.cec.com.cn/position?positionType=0"
    assert row["url_scope"] == "project_listing"
    assert jobs_db.execute("SELECT url FROM job").fetchone()[0] == old_url


@pytest.mark.parametrize("legacy", [False, True])
def test_text_summary_counts_nonempty_bodies_with_legacy_sqlite_fallback(jobs_db, text_db, legacy):
    rows = [make_job(1, description="正文"), make_job(2, requirements="硕士及以上"),
            make_job(3), make_job(4, description=""), make_job(5, description="\x00"),
            make_job(6, apply_end="2026-10-31", description="过期正文")]
    ingest_run(jobs_db, "s1", rows, ts=T(1))
    upsert_texts(text_db, rows, ts=T(1))
    class LegacySQLite:
        def execute(self, sql, *args):
            if sql == "SELECT octet_length('')":
                raise sqlite3.OperationalError("no such function: octet_length")
            return text_db.execute(sql, *args)
    summary = q.data_summary(jobs_db, LegacySQLite() if legacy else text_db)
    assert summary["open_jobs"] == 5 and summary["with_jd_text"] == 3
    assert summary["jd_observation"]["older_than_48h"] == 3
