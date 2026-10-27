"""`export_job_evidence` 的离线测试：只导接口字段，不做推断。

这一层存在的理由是把热招（大易）列表接口里的 `workPlaceStr` / `endDate` 带进日历。
它们原来是白抓的——数据层有城市，日历里却没有城市。这里锁住三条不变量：
  1. 哨兵值（3000-01-01）绝不能当截止日导出去；
  2. 已下架职位（closed_at 非空）不能进证据；
  3. 一家公司如果一条结构化线索都没有，就不要在文件里写空记录。
"""

import json
from pathlib import Path

from jobradar.pipeline.calendar import export_job_evidence
from jobradar.store.migrate import connect


def _mkdb(tmp_path: Path):
    conn = connect(tmp_path / "jobs.db", "jobs")
    conn.execute("INSERT INTO company(name) VALUES ('甲企业')")
    conn.execute("INSERT INTO company(name) VALUES ('乙企业')")
    return conn


def _add_job(conn, company_id, *, title, rtype, cities, apply_end=None, publish_at=None,
             grad_year=None, category=None, closed=None):
    conn.execute(
        "INSERT INTO job(company_id, source_id, source_job_id, url, title, recruit_type, "
        "grad_year, cities, category, apply_end, publish_at, first_seen, last_seen, closed_at, "
        "content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (company_id, "s1", title, "u", title, rtype, grad_year,
         json.dumps(cities, ensure_ascii=False), category, apply_end, publish_at,
         "2026-10-01", "2026-10-26", closed, f"h-{title}"),
    )
    conn.commit()


def test_export_groups_cities_by_recruit_type(tmp_path):
    conn = _mkdb(tmp_path)
    _add_job(conn, 1, title="算法工程师", rtype="campus", cities=["北京", "上海"])
    _add_job(conn, 1, title="门店店员", rtype="social", cities=["成都"])
    out = tmp_path / "ev.jsonl"
    n = export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z")
    assert n == 1
    rec = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert set(rec["cities_by_type"]) == {"campus", "social"}
    assert rec["cities_by_type"]["campus"] == ["北京", "上海"]
    assert "成都" not in rec["cities_by_type"]["campus"]


def test_closed_jobs_are_excluded(tmp_path):
    conn = _mkdb(tmp_path)
    _add_job(conn, 1, title="已下架岗位", rtype="campus", cities=["拉萨"],
             closed="2026-10-20")
    out = tmp_path / "ev.jsonl"
    export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z")
    assert out.read_text(encoding="utf-8").strip() == ""


def test_closed_job_contributes_only_its_deadline(tmp_path):
    """下架岗位的城市/方向不能进证据（不代表现在还能投什么），
    但它的截止日要留着——那正是这个批次关窗的硬证据。"""
    conn = _mkdb(tmp_path)
    _add_job(conn, 1, title="2026届秋招-算法", rtype="campus", cities=["拉萨"],
             apply_end="2026-09-30", category="技术", closed="2026-10-01")
    _add_job(conn, 1, title="2027届秋招-产品", rtype="campus", cities=["北京"],
             apply_end="2026-12-31")
    out = tmp_path / "ev.jsonl"
    export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z")
    rec = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert rec["cities_by_type"]["campus"] == ["北京"], "下架岗位的城市不能进在招城市"
    assert rec["closed_by_type"]["campus"] == ["2026-09-30"]
    assert rec["ends_by_type"]["campus"] == ["2026-12-31"]


def test_company_without_any_signal_is_skipped(tmp_path):
    conn = _mkdb(tmp_path)
    _add_job(conn, 2, title="无城市无日期", rtype="campus", cities=[])
    out = tmp_path / "ev.jsonl"
    assert export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z") == 0


def test_deadlines_and_grad_years_survive(tmp_path):
    conn = _mkdb(tmp_path)
    _add_job(conn, 1, title="2027届研发", rtype="campus", cities=["长沙"],
             apply_end="2026-11-30", publish_at="2026-10-15", grad_year=2027)
    out = tmp_path / "ev.jsonl"
    export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z")
    rec = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert rec["ends_by_type"]["campus"] == ["2026-11-30"]
    assert rec["grad_years"] == [2027]


def test_single_publish_day_is_not_a_window_start(tmp_path):
    """单条职位的上架日不是「网申起点」——有人今天补录一个岗，今天就会变成起点，这是错的。

    只有同类型里明显多数职位同一天上架（批量发布的特征）才算一批真的开放了。
    """
    conn = _mkdb(tmp_path)
    _add_job(conn, 1, title="孤零零一个岗", rtype="campus", cities=["长沙"],
             publish_at="2026-10-20")
    out = tmp_path / "ev.jsonl"
    export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z")
    rec = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert rec["starts_by_type"] == {}, "单条上架日不能被当成网申起点"


def test_bulk_publish_day_becomes_window_start(tmp_path):
    """批量发布（同一天上架 5 条、占该类型 5/6）才是可信起点。"""
    conn = _mkdb(tmp_path)
    for i in range(5):
        _add_job(conn, 1, title=f"2027届研发{i}", rtype="campus", cities=["长沙"],
                 publish_at="2026-08-03")
    _add_job(conn, 1, title="后来补录的岗", rtype="campus", cities=["长沙"],
             publish_at="2026-10-20")
    out = tmp_path / "ev.jsonl"
    export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z")
    rec = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert rec["starts_by_type"]["campus"] == ["2026-08-03"]
    assert "2026-10-20" not in rec["starts_by_type"]["campus"]


def test_deadlines_are_ranked_by_count_not_by_date(tmp_path):
    """截止日要取**最多岗位**的那天，不是最早那天。

    2026-10-26 实测赛诺菲：social 有 86 个不同截止日，最早的三个是 10-27/10-28/10-29
    （各几条岗位），真正的批次收口是 11-30（117 条）。原来是 `sorted(v)[:3]`，
    日历上就会写成一个毫无代表性的日期。
    """
    conn = _mkdb(tmp_path)
    # 1 条 10-27，20 条 11-30，1 条 12-31
    _add_job(conn, 1, title="零星岗", rtype="social", cities=["上海"], apply_end="2026-10-27")
    for i in range(20):
        _add_job(conn, 1, title=f"批次岗{i}", rtype="social", cities=["上海"],
                 apply_end="2026-11-30")
    _add_job(conn, 1, title="长尾岗", rtype="social", cities=["上海"], apply_end="2026-12-31")
    out = tmp_path / "ev.jsonl"
    export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z")
    rec = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    ends = rec["ends_by_type"]["social"]
    assert "2026-11-30" in ends, f"票数最高的截止日必须出现：{ends}"
    assert len(ends) <= 3


def test_each_recruit_type_keeps_its_own_top3(tmp_path):
    """各类型**各自**取 top-3，不能被大类型挤掉。

    如果先对全局取 most_common(3) 再按类型过滤，只有 2 条岗位的 campus
    在 social 有 96 个日期的情况下会被整类挤成空数组（2026-10-26 实测赛诺菲）。
    """
    conn = _mkdb(tmp_path)
    for i in range(50):
        _add_job(conn, 1, title=f"社招{i}", rtype="social", cities=["上海"],
                 apply_end=f"2026-11-{i % 28 + 1:02d}")
    _add_job(conn, 1, title="2027届管培", rtype="campus", cities=["上海"], apply_end="2026-12-05")
    _add_job(conn, 1, title="2027届技术", rtype="campus", cities=["上海"], apply_end="2026-12-06")
    out = tmp_path / "ev.jsonl"
    export_job_evidence(conn, out, ts="2026-10-26T03:00:00Z")
    rec = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert rec["ends_by_type"]["campus"] == ["2026-12-05", "2026-12-06"], rec["ends_by_type"]
    assert rec["ends_by_type"]["social"]
