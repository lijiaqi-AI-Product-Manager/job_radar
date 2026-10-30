"""查询层：agent 看到的所有答案都从这里出来。错了就是"看似权威的胡说"，所以测试要细。"""

import pytest

from helpers import T, make_job
from jobradar.core.queries import (
    company_trend,
    compare_roles,
    data_as_of,
    data_status,
    field_coverage,
    get_job,
    new_jobs_by_category,
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


def test_search_by_company_alias(jobs_db):
    """用户说「中核」，库里是「中国核工业集团」：简称要能命中（评测 neg-05）。"""
    ingest_run(jobs_db, "s3", [make_job(1, source_id="s3", company="中国核工业集团", title="核工程研发")], ts=T(1))
    assert titles(search_jobs(jobs_db, company="中核")) == ["核工程研发"]
    assert titles(search_jobs(jobs_db, company="中国核工业集团")) == ["核工程研发"]


def test_company_alias_does_not_fuzzy_match(jobs_db):
    """映射表里没有的说法保持原样，不做模糊猜测。"""
    ingest_run(jobs_db, "s3", [make_job(1, source_id="s3", company="中国核工业集团", title="核工程研发")], ts=T(1))
    assert search_jobs(jobs_db, company="中核集团") == []
    assert titles(search_jobs(jobs_db, company="核工业")) == ["核工程研发"]


def test_recent_changes_by_company_alias(jobs_db):
    ingest_run(jobs_db, "s3", [make_job(1, source_id="s3", company="中国核工业集团", title="核工程研发")], ts=T(1))
    rows = recent_changes(jobs_db, since=T(0), company="中核")
    assert [r["title"] for r in rows] == ["核工程研发"]


def test_company_prefix_extension_does_not_return_another_company(jobs_db):
    """`--company 京东` 不能返回「京东方」的岗位（2026-10-24 外部评审 P0：200+ 行别家数据）。

    京东不在数据集里，京东方是另一家公司。子串只多一个字的「前缀延伸」不敢猜，
    返回空 + 候选，让用户知道是「未收录」而不是「京东在招 200 个岗」。
    """
    ingest_run(jobs_db, "boe", [make_job(1, source_id="boe", company="京东方", title="面板工艺工程师")], ts=T(1))
    meta = {}
    assert search_jobs(jobs_db, company="京东", meta=meta) == []
    assert meta["company_match"]["match"] == "none"
    assert meta["company_match"]["candidates"] == ["京东方"]


def test_ambiguous_company_term_returns_nothing_and_lists_candidates(jobs_db):
    """「中国」命中多家时不能随手挑一家，也不能把 30 家混在一起返回。"""
    ingest_run(jobs_db, "a", [make_job(1, source_id="a", company="中国核工业集团", title="核工程")], ts=T(1))
    ingest_run(jobs_db, "b", [make_job(1, source_id="b", company="中国船舶集团", title="船舶设计")], ts=T(1))
    meta = {}
    assert search_jobs(jobs_db, company="中国", meta=meta) == []
    assert meta["company_match"]["match"] == "ambiguous"
    assert meta["company_match"]["candidates"] == ["中国核工业集团", "中国船舶集团"]


def test_company_contains_flag_allows_group_query(jobs_db):
    """显式 `--contains` 才是「按子串搜」，此时多家结果是有意的。"""
    ingest_run(jobs_db, "a", [make_job(1, source_id="a", company="中国核工业集团", title="核工程")], ts=T(1))
    ingest_run(jobs_db, "b", [make_job(1, source_id="b", company="中国船舶集团", title="船舶设计")], ts=T(1))
    meta = {}
    assert len(search_jobs(jobs_db, company="中国", contains=True, meta=meta)) == 2
    assert meta["company_match"]["match"] == "contains"


def test_company_match_mode_is_reported_for_exact_and_alias(jobs_db):
    """命中方式要能回显，agent 才知道「这是精确匹配」还是「猜的」。"""
    ingest_run(jobs_db, "s3", [make_job(1, source_id="s3", company="中国核工业集团", title="核工程研发")], ts=T(1))
    exact, alias = {}, {}
    search_jobs(jobs_db, company="中国核工业集团", meta=exact)
    search_jobs(jobs_db, company="中核", meta=alias)
    assert exact["company_match"] == {"match": "exact", "matched": ["中国核工业集团"]}
    assert alias["company_match"]["match"] == "alias"
    assert alias["company_match"]["matched"] == ["中国核工业集团"]


def test_search_dedupe_collapses_identical_reqs(jobs_db):
    """同一 ATS 岗位开成多条 req（同公司+同标题+同城市）时，--dedupe 折叠并给出原条数。

    全库实测 9.2% 是这种重复（星巴克门店岗一家 2,907 条），默认不折叠（计数口径不变），
    但用户问"这家公司在招几个岗"时要能拿到折叠后的数字。
    """
    dup = [make_job(i, title="门店储备干部", cities=["上海"]) for i in range(1, 4)]
    keep = make_job(9, title="区域经理", cities=["上海"])
    ingest_run(jobs_db, "s1", [*dup, keep], ts=T(1))
    assert len(search_jobs(jobs_db)) == 4
    rows = search_jobs(jobs_db, dedupe=True)
    assert len(rows) == 2
    by_title = {r["title"]: r for r in rows}
    assert by_title["门店储备干部"]["variants"] == 3
    assert by_title["区域经理"]["variants"] == 1
    assert "_rn" not in rows[0]


def test_search_dedupe_ignores_city_order_and_repeated_city_labels(jobs_db):
    jobs = [make_job(1, title="算法研发", cities=["北京", "上海"]),
            make_job(2, title="算法研发", cities=["上海", "北京"]),
            make_job(3, title="算法研发", cities=["北京", "上海", "上海"]),
            make_job(4, title="算法研发", cities=["深圳"])]
    ingest_run(jobs_db, "s1", jobs, ts=T(1))
    rows = search_jobs(jobs_db, dedupe=True)
    assert [(r["id"], r["variants"]) for r in rows] == [("s1:1", 3), ("s1:4", 1)]


def test_diff_by_category_respects_company(jobs_db):
    """`diff --by category --company 某公司` 曾静默忽略 --company，把全库数字当该公司的。"""
    ingest_run(jobs_db, "a", [make_job(i, source_id="a", company="腾讯", category="技术") for i in range(1, 4)], ts=T(1))
    ingest_run(jobs_db, "b", [make_job(1, source_id="b", company="美团", category="产品")], ts=T(1))
    meta = {}
    rows = new_jobs_by_category(jobs_db, since=T(0), company="腾讯", meta=meta)
    assert rows == [{"category": "技术", "n": 3}]
    assert meta["company_match"]["match"] == "exact"
    # 不带 --company 时仍是全库
    assert sum(r["n"] for r in new_jobs_by_category(jobs_db, since=T(0))) == 4


def test_alias_table_only_maps_unique_short_names():
    from jobradar.aliases import match_names
    assert match_names("中核") == ["中核", "中国核工业集团"]
    assert match_names("腾讯") == ["腾讯"]
    assert match_names("  中核  ") == ["中核", "中国核工业集团"]


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


def test_compare_roles_by_jd_text(jobs_db, text_db):
    """「谁最看重论文」这类问题要按 JD 原文取岗位，而不是标题关键词（评测 compare-04）。"""
    a = [make_job(1, company="腾讯", subcategory="算法", requirements="有顶会论文者优先"),
         make_job(2, company="腾讯", subcategory="算法", requirements="熟悉 Go")]
    b = [make_job(1, source_id="s2", company="美团", subcategory="算法", requirements="扎实的编程基础")]
    ingest_run(jobs_db, "s1", a, ts=T(1))
    ingest_run(jobs_db, "s2", b, ts=T(1))
    upsert_texts(text_db, a + b, ts=T(1))

    out = compare_roles(jobs_db, text_db, ["腾讯", "美团"], text="论文")
    assert [j["requirements"] for j in out["腾讯"]] == ["有顶会论文者优先"]
    assert out["美团"] == []


def test_compare_roles_needs_a_selector(jobs_db, text_db):
    import pytest
    with pytest.raises(ValueError):
        compare_roles(jobs_db, text_db, ["腾讯"])


def test_new_jobs_by_category(jobs_db):
    """回答"最近哪类职位新增最多"（评测 trend-02）。"""
    ingest_run(jobs_db, "s1", [make_job(1, category="技术", subcategory="后端"),
                               make_job(2, category="技术", subcategory="算法"),
                               make_job(3, category="产品")], ts=T(1))
    assert new_jobs_by_category(jobs_db, since=T(0)) == [
        {"category": "技术", "n": 2}, {"category": "产品", "n": 1}]


def test_new_jobs_by_category_buckets_unclassified(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, category=None, subcategory=None)], ts=T(1))
    assert new_jobs_by_category(jobs_db, since=T(0)) == [{"category": "未分类", "n": 1}]


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


def test_stale_threshold_agrees_with_envelope(jobs_db, monkeypatch):
    """`sources` 的 stale 与 envelope 的 stale 必须是同一个阈值（以前 36h vs 48h）。

    40 小时没成功抓取：还没到「两个日报周期」，两边都算新鲜；50 小时两边都算过期。
    """
    from jobradar import local

    ingest_run(jobs_db, "s1", [make_job(1)], ts="2026-10-20T00:00:00Z")
    for now, expect in (("2026-10-21T16:00:00Z", False),    # +40h
                        ("2026-10-22T02:00:00Z", True)):     # +50h
        monkeypatch.setattr(local, "now_ts", lambda now=now: now)
        assert data_status(jobs_db, now=now)[0]["stale"] is expect
        assert local.envelope(jobs_db, [])["stale"] is expect


def test_data_status_reports_duration_and_error(jobs_db):
    """抓得慢/坏在哪要能看出来：source_run.duration_s 以前永远是 NULL。"""
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1), duration_s=12.5)
    ingest_run(jobs_db, "s1", [], ts=T(2), ok=False, error="ReadTimeout", duration_s=30.0)
    row = data_status(jobs_db, now=T(2))[0]
    assert row["last_status"] == "failed" and row["error"] == "ReadTimeout"
    assert row["duration_s"] == 30.0 and row["last_ok"] == T(1)


def test_data_status_summary_is_compact(jobs_db):
    """277 行整表约 52KB（15k tokens），summary 只给计数 + 有问题的源。"""
    from jobradar.core.queries import data_status_summary

    ingest_run(jobs_db, "ok-src", [make_job(1, source_id="ok-src")], ts=T(1))
    ingest_run(jobs_db, "bad-src", [], ts=T(1), ok=False, error="boom")
    rows = data_status(jobs_db, now=T(1))
    s = data_status_summary(rows)
    assert s["counts"] == {"sources": 2, "ok": 1, "failed": 1, "rejected": 0, "stale": 1, "open_jobs": 1}
    assert [p["source_id"] for p in s["problems"]] == ["bad-src"]
    assert s["slowest"] == []          # duration_s 为 NULL 时不编造耗时


def test_compare_roles_by_keyword(jobs_db, text_db):
    a = [make_job(1, company="药明康德", title="【2027校招】化学研发研究员", subcategory=None, category=None, requirements="有机化学"),
         make_job(2, company="药明康德", title="财务专员", subcategory=None, category=None)]
    ingest_run(jobs_db, "s1", a, ts=T(1))
    upsert_texts(text_db, a, ts=T(1))
    out = compare_roles(jobs_db, text_db, ["药明康德"], keyword="研发")
    assert [j["title"] for j in out["药明康德"]] == ["【2027校招】化学研发研究员"]
    assert out["药明康德"][0]["requirements"] == "有机化学"


def test_compare_roles_requires_category_or_keyword(jobs_db, text_db):
    with pytest.raises(ValueError):
        compare_roles(jobs_db, text_db, ["x"])


@pytest.fixture
def jd_seeded(jobs_db, text_db):
    a = [make_job(1, company="腾讯", title="算法工程师", requirements="精通 PyTorch，熟悉 CUDA 优化"),
         make_job(2, company="腾讯", title="后端开发", description="负责推荐系统后台", requirements="熟悉 Go 与 Kafka"),
         make_job(3, company="腾讯", title="PyTorch 框架研发", requirements="C++"),
         make_job(4, company="腾讯", title="产品经理")]  # 无 JD
    b = [make_job(1, source_id="s2", company="美团", title="机器学习工程师", requirements="pytorch / TensorFlow")]
    ingest_run(jobs_db, "s1", a, ts=T(1))
    ingest_run(jobs_db, "s2", b, ts=T(1))
    upsert_texts(text_db, a + b, ts=T(1))
    return jobs_db, text_db


def test_search_text_matches_jd_and_title(jd_seeded):
    jobs, text = jd_seeded
    got = search_jobs(jobs, text="PyTorch", text_conn=text)
    assert sorted(titles(got)) == ["PyTorch 框架研发", "机器学习工程师", "算法工程师"]  # JD 命中 + 标题命中，不分大小写


def test_search_text_multiple_terms_are_and(jd_seeded):
    jobs, text = jd_seeded
    assert titles(search_jobs(jobs, text="PyTorch CUDA", text_conn=text)) == ["算法工程师"]
    assert titles(search_jobs(jobs, text="推荐 Kafka", text_conn=text)) == ["后端开发"]  # 跨职责与要求


def test_search_text_combines_with_filters_and_gives_snippet(jd_seeded):
    jobs, text = jd_seeded
    [r] = search_jobs(jobs, text="pytorch", company="美团", text_conn=text)
    assert r["title"] == "机器学习工程师" and "pytorch" in r["match"]
    [t] = search_jobs(jobs, text="框架", text_conn=text)
    assert t["match"] is None  # 只命中标题时没有 JD 片段


def test_search_text_requires_text_db(jd_seeded):
    jobs, _ = jd_seeded
    with pytest.raises(ValueError):
        search_jobs(jobs, text="Go")
def test_field_coverage_reports_missing_city_and_grad_year(jobs_db):
    """城市/届次缺失是来源没给：stats 要把覆盖率报出来，别让 agent 以为"没有"。"""
    ingest_run(jobs_db, "s1", [
        make_job(1, cities=["深圳"], grad_year=2027, category="技术"),
        make_job(2, cities=[], grad_year=None, category=None, degree_min=None),
        make_job(3, recruit_type="social", cities=[], grad_year=None),
    ], ts=T(20))
    cov = field_coverage(jobs_db)
    assert cov["cities"] == 0.333 and cov["grad_year"] == 0.333 and cov["category"] == 0.667
    assert cov["campus_cities"] == 0.5 and cov["campus_grad_year"] == 0.5  # 只统计 campus 两条


def test_field_coverage_reports_dates_too(jobs_db):
    """日期覆盖率和城市一样要报：日历条目要「网申时间 X ~ Y」这一段。

    之前只报 cities/grad_year/category/degree_min，agent 拿到的字段可靠性画像里
    完全没有日期，会默认日期是全的——实测全库 publish_at 只有个位数百分比。
    """
    ingest_run(jobs_db, "s1", [
        make_job(1, cities=["深圳"], publish_at="2026-09-01", apply_end="2026-12-31"),
        make_job(2, cities=[], publish_at=None, apply_end=None),
    ], ts=T(20))
    cov = field_coverage(jobs_db)
    assert cov["publish_at"] == 0.5 and cov["apply_end"] == 0.5


def test_exclude_store_drops_retail_posts(jobs_db):
    """喜茶/星巴克门店帖约 8 千条；校招用户用 --exclude-store 排掉，但默认不过滤。"""
    ingest_run(jobs_db, "tea", [
        make_job(1, source_id="tea", company="喜茶", title="门店店员（上海）"),
        make_job(2, source_id="tea", company="喜茶", title="品牌营销管培生"),
    ], ts=T(1))
    assert len(search_jobs(jobs_db)) == 2
    rows = search_jobs(jobs_db, exclude_store=True)
    assert [r["title"] for r in rows] == ["品牌营销管培生"]


def test_search_deadline_filters_only_known_deadlines(jobs_db):
    """截止日筛选只作用在「确实写了截止日」的岗位上。

    没有截止日的岗位（北森门户全部）不能被 deadline_after 当成「还在招」放进来，
    也不能被 deadline_before 当成「已过期」排除——两种都会误导用户。
    """
    ingest_run(jobs_db, "s1", [
        make_job(1, apply_end="2026-11-10"),
        make_job(2, apply_end="2027-03-01"),
        make_job(3),                      # 源没给截止日
    ], ts=T(1))
    soon = search_jobs(jobs_db, deadline_before="2026-12-31", limit=10)
    assert [r["id"] for r in soon] == ["s1:1"]
    later = search_jobs(jobs_db, deadline_after="2027-01-01", limit=10)
    assert [r["id"] for r in later] == ["s1:2"]
    # 不传截止日条件时三条都在（未知截止日 ≠ 已截止）
    assert len(search_jobs(jobs_db, limit=10)) == 3
