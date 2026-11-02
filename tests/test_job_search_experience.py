"""截止优先、名称匹配和正文证据在各查询入口保持一致。"""

from itertools import chain, repeat

import pytest

from helpers import T, make_job
from jobradar.aliases import match_names
from jobradar.core import queries as q
from jobradar.pipeline import calendar as cal
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import connect


@pytest.mark.parametrize("dedupe", [False, True])
@pytest.mark.parametrize("bounds", [
    {"deadline_before": "2026-11-30"},
    {"deadline_after": "2026-11-01"},
    {"deadline_after": "2026-11-01", "deadline_before": "2026-11-30"},
])
def test_deadline_search_puts_urgent_jobs_before_newer_posts(jobs_db, dedupe, bounds):
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-11-02")], ts=T(1))
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-11-02"),
                              make_job(2, apply_end="2026-11-20"), make_job(3)], ts=T(2))
    meta = {}
    rows = q.search_jobs(jobs_db, limit=1, dedupe=dedupe, meta=meta, **bounds)
    assert [r["id"] for r in rows] == ["s1:1"]
    assert meta["total"] == 2 and meta["truncated"] is True
    assert [r["id"] for r in q.search_jobs(jobs_db, limit=3)] == ["s1:2", "s1:3", "s1:1"]


def test_deadline_ties_have_stable_order_and_keep_history_explicit(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-11-01"),
                              make_job(2, apply_end="2026-11-10")], ts=T(1))
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-11-01"),
                              make_job(2, apply_end="2026-11-10"),
                              make_job(3, apply_end="2026-11-10"),
                              make_job(4, apply_end="2026-11-10")], ts=T(2))
    assert [r["id"] for r in q.search_jobs(jobs_db, deadline_before="2026-11-30")] == [
        "s1:1", "s1:3", "s1:4", "s1:2"]
    assert [r["id"] for r in q.search_jobs(jobs_db, deadline_before="2026-11-30",
                                          include_closed=True)] == ["s1:1", "s1:3", "s1:4", "s1:2"]


@pytest.mark.parametrize("term", ["P&G", "p&g", "Ｐ＆Ｇ", "Procter & Gamble", "procter & gamble"])
def test_registered_english_brand_returns_same_company(jobs_db, term):
    ingest_run(jobs_db, "s1", [make_job(1, company="宝洁")], ts=T(1))
    ingest_run(jobs_db, "s2", [make_job(1, source_id="s2", company="宝洁供应服务公司")], ts=T(1))
    meta = {}
    assert [r["id"] for r in q.search_jobs(jobs_db, company=term, meta=meta)] == ["s1:1"]
    assert meta["company_match"]["match"] == "alias"
    assert match_names(term)[-1] == "宝洁"


def test_registered_brand_does_not_claim_a_similarly_named_company(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, company="宝洁供应服务公司")], ts=T(1))
    meta = {}
    assert q.search_jobs(jobs_db, company="P&G", meta=meta) == []
    assert meta["company_match"]["match"] == "none"


@pytest.mark.parametrize("alias, company", [("铁建", "中国铁建国际"), ("中移动", "中国移动研究院")])
def test_registered_group_name_does_not_silently_select_a_subsidiary(jobs_db, alias, company):
    ingest_run(jobs_db, "s1", [make_job(1, company=company)], ts=T(1))
    meta = {}
    assert q.search_jobs(jobs_db, company=alias, meta=meta) == []
    assert meta["company_match"]["candidates"] == [company]
    assert [r["company"] for r in q.search_jobs(jobs_db, company=company)] == [company]


@pytest.mark.parametrize("selector", [{"category": "技术"}, {"text": "Python"}])
def test_compare_preserves_body_observation_time(jobs_db, text_db, selector):
    job = make_job(1, description="Python 开发职责")
    ingest_run(jobs_db, "s1", [job], ts=T(28))
    upsert_texts(text_db, [job], ts=T(1))
    rows = q.compare_roles(jobs_db, text_db, ["腾讯"], **selector)["腾讯"]
    assert rows[0]["last_seen"] == T(28)
    assert rows[0]["text_observed_at"] == T(1)
    assert rows[0]["description"] == "Python 开发职责"


def test_fulltext_snippet_carries_its_body_observation_time(jobs_db, text_db):
    jobs = [make_job(1, description="Python 开发职责"), make_job(2, title="Python 工程师")]
    ingest_run(jobs_db, "s1", jobs, ts=T(28))
    upsert_texts(text_db, jobs[:1], ts=T(1))
    rows = {r["id"]: r for r in q.search_jobs(jobs_db, text_conn=text_db, text="Python")}
    assert rows["s1:1"]["match"] and rows["s1:1"]["text_observed_at"] == T(1)
    assert rows["s1:2"]["match"] is None and rows["s1:2"]["text_observed_at"] is None


def test_compare_missing_body_has_no_invented_observation_time(jobs_db, text_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(28))
    row = q.compare_roles(jobs_db, text_db, ["腾讯"], category="技术")["腾讯"][0]
    assert row["description"] is row["requirements"] is row["text_observed_at"] is None


def test_calendar_product_hint_finds_its_parent_group(tmp_path, jobs_db):
    conn = connect(tmp_path / "calendar.db", "calendar")
    entry = cal.ManualEntry(id="byteintern", group="字节跳动", company="字节跳动",
                            product="ByteIntern", project_type="暑期实习", grad_year=2027,
                            apply_url="https://jobs.bytedance.com/campus/position",
                            source={"type": "official_site", "name": "招聘官网"}, as_of="2026-10-21")
    brand = cal.ManualEntry(id="brand", group="宝洁", company="宝洁", project_type="校招",
                            source={"type": "official_site", "name": "招聘官网"}, as_of="2026-10-21")
    cal.build(conn, jobs_db, manual=[entry, brand], sources=[], targets={"sectors": {}}, ts=T(22))
    hint = q.calendar_hint(conn, "ByteIntern")
    assert hint and hint["entries"] == 1 and hint["grad_years"] == [2027]
    assert hint["cli_hint"] == "jobradar calendar --company ByteIntern --table"
    assert q.calendar_hint(conn, "P&G")["cli_hint"] == "jobradar calendar --group 宝洁 --table"
    conn.close()


def test_calendar_hint_reports_all_batches_not_just_the_first_page(tmp_path, jobs_db):
    conn = connect(tmp_path / "calendar.db", "calendar")
    entries = [cal.ManualEntry(id=f"batch-{i}", group="独立公司", project_type="校招",
                               grad_year=2027, source={"type": "official_site", "name": "招聘官网"},
                               as_of="2026-10-21") for i in range(23)]
    cal.build(conn, jobs_db, manual=entries, sources=[], targets={"sectors": {}}, ts=T(22))
    assert q.calendar_hint(conn, "独立公司")["entries"] == 23
    conn.close()


def test_calendar_alias_and_blocked_hint_keep_employer_identity(tmp_path, jobs_db):
    conn = connect(tmp_path / "calendar.db", "calendar")
    entries = [cal.ManualEntry(id="subsidiary", group="中国移动研究院", project_type="校招",
                               source={"type": "official_site", "name": "招聘官网"}, as_of="2026-10-21")]
    targets = {"sectors": {"企业": ["京东", "京东方", "中国移动研究院"]},
               "blocked": {"京东方": "来源不可读取", "中国移动研究院": "仅公开入口"}}
    cal.build(conn, jobs_db, manual=entries, sources=[], targets=targets, ts=T(22))
    assert q.calendar_entries(conn, group="中移动") == []
    assert q.calendar_hint(conn, "中移动") is None
    assert q.calendar_blocked_reason(conn, "京东") is None
    assert q.calendar_blocked_reason(conn, "%") is None
    assert q.calendar_blocked_reason(conn, "京东方") == "来源不可读取"
    conn.close()


def test_search_does_not_expire_its_own_result_across_midnight(jobs_db, monkeypatch):
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-11-02")], ts="2026-11-02T15:00:00Z")
    clock = chain(["2026-11-02T15:59:59Z"], repeat("2026-11-02T16:00:00Z"))
    monkeypatch.setattr(q, "now_ts", lambda: next(clock))
    meta = {}
    rows = q.search_jobs(jobs_db, company="腾讯", meta=meta)
    assert len(rows) == meta["company_coverage"]["visible_jobs"] == 1
    assert rows[0]["availability"] == "observed_recently"


@pytest.mark.parametrize("kind", ["search", "detail"])
def test_disabled_source_is_not_confirmed_by_a_recent_old_observation(jobs_db, text_db, monkeypatch, kind):
    from jobradar import source_catalog

    ingest_run(jobs_db, "s1", [make_job(1)], ts="2026-11-01T00:00:00Z")
    monkeypatch.setattr(source_catalog, "catalog", lambda: {"s1": {"enabled": False,
                        "source_kind": "aggregator", "record_kind": "recruitment_notice"}})
    before = tuple(jobs_db.execute("SELECT * FROM job WHERE id='s1:1'").fetchone())
    row = q.search_jobs(jobs_db)[0] if kind == "search" else q.get_job(jobs_db, text_db, "s1:1")
    assert row["source_enabled"] is False
    assert row["source_stale"] is False
    assert row["availability"] == "unconfirmed_disabled"
    assert row["source_last_ok"] == "2026-11-01T00:00:00Z"
    assert tuple(jobs_db.execute("SELECT * FROM job WHERE id='s1:1'").fetchone()) == before
