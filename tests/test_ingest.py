"""采集结果入库的核心逻辑：新增/变更/下架/重开，以及防止"抓取故障被当成岗位下架"。
这是整个项目里最容易出隐蔽错误的地方，改动前先读完这些测试。"""

import json

from helpers import T, make_job
from jobradar.pipeline.ingest import ingest_run, upsert_texts


def events(conn):
    return [(r["job_id"], r["type"]) for r in conn.execute("SELECT job_id, type FROM job_event ORDER BY id")]


def job_row(conn, jid):
    return conn.execute("SELECT * FROM job WHERE id=?", (jid,)).fetchone()


def test_new_jobs_are_opened(jobs_db):
    res = ingest_run(jobs_db, "s1", [make_job(1), make_job(2)], ts=T(1))
    assert (res.status, res.opened) == ("ok", 2)
    assert events(jobs_db) == [("s1:1", "open"), ("s1:2", "open")]
    r = job_row(jobs_db, "s1:1")
    assert (r["first_seen"], r["last_seen"], r["closed_at"]) == (T(1), T(1), None)
    assert json.loads(r["cities"]) == ["深圳"]


def test_unchanged_job_only_updates_last_seen(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    res = ingest_run(jobs_db, "s1", [make_job(1)], ts=T(2))
    assert (res.opened, res.changed) == (0, 0)
    assert events(jobs_db) == [("s1:1", "open")]
    r = job_row(jobs_db, "s1:1")
    assert (r["first_seen"], r["last_seen"]) == (T(1), T(2))


def test_changed_field_emits_change_event_with_field_names(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    res = ingest_run(jobs_db, "s1", [make_job(1, title="新标题", cities=["北京"])], ts=T(2))
    assert res.changed == 1
    ev = jobs_db.execute("SELECT * FROM job_event WHERE type='change'").fetchone()
    assert set(json.loads(ev["diff"])["fields"]) == {"title"}.union({"cities"})
    assert job_row(jobs_db, "s1:1")["title"] == "新标题"


def test_text_only_change_is_reported_as_text(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, requirements="旧")], ts=T(1))
    ingest_run(jobs_db, "s1", [make_job(1, requirements="新")], ts=T(2))
    ev = jobs_db.execute("SELECT diff FROM job_event WHERE type='change'").fetchone()
    assert json.loads(ev["diff"])["fields"] == ["text"]


def test_city_order_is_not_a_change(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, cities=["北京", "上海"])], ts=T(1))
    res = ingest_run(jobs_db, "s1", [make_job(1, cities=["上海", "北京"])], ts=T(2))
    assert res.changed == 0


def test_job_closes_only_after_three_consecutive_missing_successful_runs(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2)], ts=T(1))
    ingest_run(jobs_db, "s1", [make_job(2)], ts=T(2))
    ingest_run(jobs_db, "s1", [make_job(2)], ts=T(3))
    assert job_row(jobs_db, "s1:1")["closed_at"] is None
    res = ingest_run(jobs_db, "s1", [make_job(2)], ts=T(4))
    assert res.closed == 1
    assert job_row(jobs_db, "s1:1")["closed_at"] == T(4)
    assert ("s1:1", "close") in events(jobs_db)


def test_reappearing_job_resets_miss_count(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2)], ts=T(1))
    ingest_run(jobs_db, "s1", [make_job(2)], ts=T(2))
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2)], ts=T(3))
    assert job_row(jobs_db, "s1:1")["miss_count"] == 0
    ingest_run(jobs_db, "s1", [make_job(2)], ts=T(4))
    ingest_run(jobs_db, "s1", [make_job(2)], ts=T(5))
    assert job_row(jobs_db, "s1:1")["closed_at"] is None  # 计数已被重置，才缺席 2 次


def test_closed_job_that_returns_is_reopened(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2)], ts=T(1))
    for d in (2, 3, 4):
        ingest_run(jobs_db, "s1", [make_job(2)], ts=T(d))
    res = ingest_run(jobs_db, "s1", [make_job(1), make_job(2)], ts=T(5))
    assert res.reopened == 1
    r = job_row(jobs_db, "s1:1")
    assert (r["closed_at"], r["miss_count"]) == (None, 0)
    assert events(jobs_db)[-1] == ("s1:1", "reopen")
    assert r["first_seen"] == T(1)  # 首次出现时间不变


def test_failed_run_changes_nothing_and_is_logged(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    for d in (2, 3, 4, 5):
        res = ingest_run(jobs_db, "s1", [], ts=T(d), ok=False, error="timeout")
        assert res.status == "failed"
    r = job_row(jobs_db, "s1:1")
    assert (r["closed_at"], r["miss_count"], r["last_seen"]) == (None, 0, T(1))
    runs = jobs_db.execute("SELECT status, error FROM source_run WHERE status='failed'").fetchall()
    assert len(runs) == 4 and runs[0]["error"] == "timeout"


def test_empty_result_for_known_source_is_rejected(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    res = ingest_run(jobs_db, "s1", [], ts=T(2))
    assert res.status == "rejected"
    assert job_row(jobs_db, "s1:1")["miss_count"] == 0


def test_empty_result_allowed_when_explicit(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    res = ingest_run(jobs_db, "s1", [], ts=T(2), allow_empty=True)
    assert res.status == "ok"
    assert job_row(jobs_db, "s1:1")["miss_count"] == 1


def test_circuit_breaker_on_large_drop(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(i) for i in range(10)], ts=T(1))
    res = ingest_run(jobs_db, "s1", [make_job(i) for i in range(4)], ts=T(2))  # 掉了 60%
    assert res.status == "rejected"
    assert jobs_db.execute("SELECT SUM(miss_count) FROM job").fetchone()[0] == 0
    assert jobs_db.execute("SELECT status FROM source_run ORDER BY id DESC").fetchone()[0] == "rejected"


def test_drop_of_exactly_threshold_is_accepted(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(i) for i in range(10)], ts=T(1))
    res = ingest_run(jobs_db, "s1", [make_job(i) for i in range(5)], ts=T(2))
    assert res.status == "ok"


def test_sources_are_isolated(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    ingest_run(jobs_db, "s2", [make_job(1, source_id="s2", company="阿里")], ts=T(1))
    for d in (2, 3, 4):
        ingest_run(jobs_db, "s2", [make_job(9, source_id="s2", company="阿里")], ts=T(d))
    assert job_row(jobs_db, "s1:1")["closed_at"] is None
    assert job_row(jobs_db, "s2:1")["closed_at"] == T(4)


def test_duplicate_ids_within_one_run_are_collapsed(jobs_db):
    res = ingest_run(jobs_db, "s1", [make_job(1), make_job(1, title="后者生效")], ts=T(1))
    assert res.opened == 1
    assert job_row(jobs_db, "s1:1")["title"] == "后者生效"


def test_company_rows_are_shared(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2)], ts=T(1))
    assert jobs_db.execute("SELECT COUNT(*) FROM company").fetchone()[0] == 1


def test_upsert_texts(jobs_db, text_db):
    jobs = [make_job(1, description="D", requirements="R")]
    assert upsert_texts(text_db, jobs, ts=T(1)) == 1
    upsert_texts(text_db, [make_job(1, description="D2", requirements="R2")], ts=T(2))
    r = text_db.execute("SELECT * FROM job_text WHERE job_id='s1:1'").fetchone()
    assert (r["description"], r["requirements"], r["fetched_at"]) == ("D2", "R2", T(2))

def test_expected_max_absorbs_the_drop_caused_by_a_new_page_cap(jobs_db):
    """给源加 max_pages 限额后，岗位数会从「历史全量」掉到「限额」，不应该被骤降保护拦下。

    真实场景：星巴克 18418 岗 → 限 30 页（3000）后，每次都判 dropped 18418 -> 3000，
    源被永久 rejected，旧岗位也永远不下架。
    """
    ingest_run(jobs_db, "s1", [make_job(i) for i in range(1, 201)], ts=T(1))
    capped = [make_job(i) for i in range(1, 100)]   # 99/200 = 49.5%，低于阈值
    assert ingest_run(jobs_db, "s1", capped, ts=T(2)).status == "rejected"          # 旧行为：拦
    res = ingest_run(jobs_db, "s1", capped, ts=T(3), expected_max=120)               # 限额生效：放行
    assert res.status == "ok"

def test_drop_is_accepted_after_repeated_rejections(jobs_db):
    """季节结束是真的会掉一半以上：连续拦 3 次后必须放行一次，否则源会永久卡死
    （rejected 不执行下架，旧岗位永远挂着，新岗位也进不来）。"""
    ingest_run(jobs_db, "s1", [make_job(i) for i in range(1, 201)], ts=T(1))
    capped = [make_job(i) for i in range(1, 100)]
    for day in (2, 3, 4):
        assert ingest_run(jobs_db, "s1", capped, ts=T(day)).status == "rejected"
    res = ingest_run(jobs_db, "s1", capped, ts=T(5))     # 第 4 次：连续 3 次被拦 → 放行
    assert res.status == "ok"


def test_empty_result_is_never_accepted_after_repeated_rejections(jobs_db):
    """「连续被拦就放行」只针对「变少了」，不针对「空了」（2026-10-24 外部评审 P0）。

    源挂了/改版返回 0 条时，放行等于把这家公司整个洗空——比旧岗位多挂几天糟得多。
    真要接受空结果，只能在源配置里显式写 params.allow_empty。
    """
    ingest_run(jobs_db, "s1", [make_job(i) for i in range(1, 201)], ts=T(1))
    for day in (2, 3, 4, 5):
        res = ingest_run(jobs_db, "s1", [], ts=T(day))
        assert res.status == "rejected"
    assert "empty" in res.reason
    open_jobs = jobs_db.execute("SELECT COUNT(*) FROM job WHERE closed_at IS NULL").fetchone()[0]
    assert open_jobs == 200


def test_expired_deadline_closes_job_automatically(jobs_db):
    """接口给了截止日且已过 → 视为下架。

    真实场景：北方华创/中国中车/长城汽车的门户不会把过期岗位摘掉，
    实测 151 条 `apply_end` 已过却仍是 `closed_at IS NULL`，
    用户搜「在招」会搜到一堆点进去显示"已截止"的岗位。
    """
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-10-10")], ts=T(1))
    # 第二轮该岗仍出现在列表里，但截止日已经过了（T(20) = 2026-10-20）
    res = ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-10-10")], ts=T(20))
    assert res.closed == 1
    assert job_row(jobs_db, "s1:1")["closed_at"] == T(20)


def test_deadline_in_future_keeps_job_open(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-12-31")], ts=T(1))
    res = ingest_run(jobs_db, "s1", [make_job(1, apply_end="2026-12-31")], ts=T(20))
    assert res.closed == 0
    assert job_row(jobs_db, "s1:1")["closed_at"] is None


def test_no_deadline_never_auto_closes(jobs_db):
    """没有截止日 ≠ 已截止。北森门户全部没有截止日，不能因此把所有岗下架。"""
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    res = ingest_run(jobs_db, "s1", [make_job(1)], ts=T(20))
    assert res.closed == 0
    assert job_row(jobs_db, "s1:1")["closed_at"] is None
