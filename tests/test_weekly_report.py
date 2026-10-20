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
