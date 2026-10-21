import importlib.util
from pathlib import Path

from helpers import T, make_job
from jobradar.pipeline.ingest import ingest_run

spec = importlib.util.spec_from_file_location(
    "weekly_report", Path(__file__).parent.parent / "scripts" / "weekly_report.py")
weekly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(weekly)


def test_weekly_report_numbers(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2, grad_year=2027)], ts=T(1))
    ingest_run(jobs_db, "s1", [make_job(1), make_job(2, grad_year=2027), make_job(3, recruit_type="social")], ts=T(10))
    for d in (11, 12, 13):
        ingest_run(jobs_db, "s1", [make_job(2, grad_year=2027), make_job(3, recruit_type="social")], ts=T(d))
    md = weekly.build(jobs_db, T(14))
    assert "2026-10-07 — 2026-10-14" in md
    assert "本周新增 1、下架 1" in md          # 岗位 3 新增于 10 日，岗位 1 于 13 日下架
    assert "当前在招 2 个岗位" in md
    assert "| 腾讯 | 1 | 0 |" in md
    assert "| 腾讯 | 1 |" in md.split("2027 届校招")[1]
    assert "开始积累" not in md                # 数据从 10-01 开始，早于本周


def test_first_week_note(jobs_db):
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(10))
    assert "开始积累" in weekly.build(jobs_db, T(14))


def test_dead_links_are_flagged_red(jobs_db):
    from jobradar.store.migrate import connect
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(10))
    cal = connect(":memory:", "calendar")
    cal.execute("""INSERT INTO entry(id, origin, group_name, project_type, source_type, source_name, as_of,
                   jd_status, apply_url) VALUES ('pdd-2027-qz','manual','拼多多','秋招正式批','official_site','官网',
                   '2026-10-21','blocked','https://example.invalid/gone')""")
    cal.execute("INSERT INTO link_check VALUES ('https://example.invalid/gone','dead',404,?,?)", (T(13), T(11)))
    cal.execute("INSERT INTO link_check VALUES ('https://example.invalid/slow','error',NULL,?,?)", (T(13), T(13)))
    md = weekly.build(jobs_db, T(14), cal_conn=cal)
    section = md.split("## 投递链接探活")[1]
    assert "🔴 https://example.invalid/gone" in section and "404" in section and "pdd-2027-qz" in section
    assert "⚠️ https://example.invalid/slow" in section
    assert "## 投递链接探活" not in weekly.build(jobs_db, T(14))  # 没有日历库时不输出该段
