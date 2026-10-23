"""发布自检脚本的判定逻辑（门槛是否达标），不依赖真实数据。"""

import importlib.util
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "release_check", Path(__file__).parent.parent / "scripts" / "release_check.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def test_data_coverage_counts_only_matched_targets():
    targets = {"sectors": {"x": ["腾讯", "京东", "京东方"]}, "aliases": {}, "blocked": {}}
    from jobradar.pipeline.calendar import match_targets
    matched = match_targets(targets, {"腾讯", "京东方"})
    assert matched["腾讯"] == ["腾讯"]
    assert matched["京东"] == []          # 京东方不能被算作京东
    assert matched["京东方"] == ["京东方"]
    covered, total = rc.data_coverage(targets, {"腾讯", "京东方"})
    assert (covered, total) == (2, 3)


def test_calendar_coverage_counts_data_or_entry(tmp_path):
    db = tmp_path / "calendar.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE target(name TEXT, data_companies TEXT, blocked_reason TEXT)")
    con.execute("CREATE TABLE entry(id TEXT, group_name TEXT)")
    con.executemany("INSERT INTO target VALUES (?,?,?)", [
        ("有数据", '["有数据的公司"]', None),
        ("有日历", "[]", None),
        ("只有blocked", "[]", "robots 禁止"),
        ("啥都没有", "[]", None),
    ])
    con.execute("INSERT INTO entry VALUES ('e1','有日历')")
    con.commit()
    con.close()
    covered, total, blocked = rc.calendar_coverage(db)
    assert (covered, total, blocked) == (2, 4, 1)


def test_campus_city_ratio(tmp_path):
    db = tmp_path / "jobs.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE job(closed_at TEXT, recruit_type TEXT, cities TEXT)")
    con.executemany("INSERT INTO job VALUES (NULL,'campus',?)", [('["北京"]',), ("[]",), (None,)])
    con.execute("INSERT INTO job VALUES (NULL,'social','[]')")
    con.commit()
    con.close()
    assert abs(rc.campus_city_ratio(db) - 1 / 3) < 1e-6


def test_jd_ratio_requires_both_dbs(tmp_path):
    assert rc.jd_ratio(tmp_path) is None
    jobs, text = tmp_path / "jobs.db", tmp_path / "jd_text.db"
    j = sqlite3.connect(jobs)
    j.execute("CREATE TABLE job(id TEXT, closed_at TEXT)")
    j.executemany("INSERT INTO job VALUES (?,NULL)", [("a",), ("b",)])
    j.commit()
    j.close()
    t = sqlite3.connect(text)
    t.execute("CREATE TABLE job_text(job_id TEXT, description TEXT, requirements TEXT)")
    t.execute("INSERT INTO job_text VALUES ('a','desc','')")
    t.commit()
    t.close()
    assert rc.jd_ratio(tmp_path) == 0.5


def test_calendar_fields_reports_manual_ratio_and_all_entries(tmp_path):
    """人工口径是发布门槛（没有数据源的公司只能靠人工条目）；全部条目口径只做展示。"""
    db = tmp_path / "calendar.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE entry (id TEXT, origin TEXT, group_name TEXT, company TEXT, grad_year INT, "
        "project_type TEXT, tracks TEXT, apply_start TEXT, apply_end TEXT, cities TEXT, apply_url TEXT, "
        "source_name TEXT, as_of TEXT)")
    base = ("某集团", "某公司", None, "校招", "[]", None, None, "[]", "https://example.invalid", "官网", "2026-10-23")
    con.execute("INSERT INTO entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ("m1", "manual", *base))  # 6 个必备字段
    con.execute("INSERT INTO entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("m2", "manual", *base[:4], '[{"direction": "技术类", "roles": ["后端"]}]', *base[5:]))  # +方向 → 达标
    con.execute("INSERT INTO entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("a1", "auto", *base[:4], '[{"direction": "技术类", "roles": []}]', *base[5:-3], '["北京"]', *base[-2:]))
    con.commit()
    con.close()
    ratio, detail, by_company = rc.calendar_fields(db)
    assert ratio == 0.5          # 2 条人工里 1 条达标
    assert "1/2" in detail and "2/3" in detail   # 人工 1/2，全部条目 2/3
    assert by_company == 1.0     # 唯一的公司有达标条目


def test_run_reports_fail_when_below_gates(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "demo.yaml").write_text(
        "defaults:\n"
        "  adapter: beisen\n"
        "  recruit_types: [campus]\n"
        "  compliance: {checked_on: '2026-10-22', robots: allowed, terms: t}\n"
        "sources:\n  - {id: s1, company: 腾讯, params: {tenant: x}}\n", encoding="utf-8")
    targets = tmp_path / "targets.yaml"
    targets.write_text("sectors: {x: [腾讯, 阿里巴巴]}\naliases: {}\nblocked: {}\n", encoding="utf-8")
    rows = rc.run(None, sources, targets, None)
    assert any(r["gate"] == "数据源覆盖" and not r["ok"] for r in rows)
    assert any(r["gate"] == "发布文档齐全" for r in rows)
