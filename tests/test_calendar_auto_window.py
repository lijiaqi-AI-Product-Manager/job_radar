"""`auto_entries` 的网申时间：数据层明明有截止日，日历上不能是空窗口。

历史缺陷：自动条目把 `apply_start` / `apply_end` 硬编码成 None，于是
`job.apply_end` 里几千条真实截止日在自己的产品里一条都看不到——
日历的「网申时间」覆盖率被自动条目按分母拉低，用户筛「11 月前截止」也筛不出来。

这里锁住五条不变量：
  1. 同批在招职位的截止日 → 自动条目取**尚未过期的那个最早截止日**
     （2026-10-26 改口径：旧版取多数，会在「6 条 11-30、5 条 12-31」时报 11-30——
     而「报名截止」的语义是"这天之前都还能投"，报最早那天才是对的）；
  2. 整批都已过期时取**最晚**那天（这批整体收口日），不能报一个更早的过去日期；
  3. 单条上架日**不是**网申起点（补录日会冒充开放日）；
  4. 多数职位同一天上架 → 那天才是起点；
  5. 整批同一天上架、且那天正好是截止日 → 那是**关窗补录**，不能当起点。
"""

import json
from datetime import date
from pathlib import Path

from jobradar.models import Compliance, SourceConfig
from jobradar.pipeline.calendar import auto_entries
from jobradar.store.migrate import connect


def _mkdb(tmp_path: Path):
    conn = connect(tmp_path / "jobs.db", "jobs")
    conn.execute("INSERT INTO company(name) VALUES ('甲企业')")
    return conn


def _add_job(conn, *, title, apply_end=None, publish_at=None, rtype="campus", cities=("北京",)):
    conn.execute(
        "INSERT INTO job(company_id, source_id, source_job_id, url, title, recruit_type, "
        "cities, apply_end, publish_at, first_seen, last_seen, content_hash) "
        "VALUES (1,'s1',?,?,?,?,?,?,?,?,?,?)",
        (title, "u", title, rtype, json.dumps(list(cities), ensure_ascii=False),
         apply_end, publish_at, "2026-10-01", "2026-10-26", f"h-{title}-{apply_end}-{publish_at}"),
    )
    conn.commit()


SOURCE = SourceConfig(id="s1", adapter="beisen", company="甲企业", params={"tenant": "jia"},
                      compliance=Compliance(checked_on=date(2026, 10, 26), robots="allow",
                                            terms="public"))


def _entries(conn):
    return auto_entries(conn, [SOURCE], {"sectors": {}}, as_of="2026-10-26T05:00:00Z")


def test_earliest_deadline_becomes_window_end(tmp_path):
    conn = _mkdb(tmp_path)
    _add_job(conn, title="后端工程师", apply_end="2026-12-31")
    _add_job(conn, title="前端工程师", apply_end="2026-11-15")
    (e,) = _entries(conn)
    assert e["apply_end"] == "2026-11-15"


def test_deadline_takes_the_majority_day_not_the_outlier(tmp_path):
    """同一批里个别岗位挂着异常日期时，截止日要听多数岗位的，不能被 min 带偏。

    2026-10-26 实测兴业证券：28 条里 1 条写 2026-09-30、多数写 2026-11-02，
    取 min 会把整批截止日提前一个月——宁可早一天的初衷，不能变成整批报错。
    """
    conn = _mkdb(tmp_path)
    for i in range(5):
        _add_job(conn, title=f"岗位{i}", apply_end="2026-11-02")
    _add_job(conn, title="异常岗位", apply_end="2026-09-30")
    (e,) = _entries(conn)
    assert e["apply_end"] == "2026-11-02"


def test_expired_dates_are_skipped_but_late_ones_kept(tmp_path):
    """一批里既有已过期岗位、又有仍在招的岗位时，截止日要报仍能投的那个。

    旧口径（众数）在这里会报 2026-09-01——用户看到「已截止」却仍在招；
    新口径报 2026-11-30，这才是「这批最晚什么时候还能投」。
    """
    conn = _mkdb(tmp_path)
    for i in range(5):
        _add_job(conn, title=f"过期{i}", apply_end="2026-09-01")
    for i in range(3):
        _add_job(conn, title=f"在招{i}", apply_end="2026-11-30")
    (e,) = _entries(conn)
    assert e["apply_end"] == "2026-11-30"


def test_all_expired_reports_the_latest_day(tmp_path):
    """整批都已过期：报最晚那天作为"这批什么时候收的口"，而不是更早的过去日期。"""
    conn = _mkdb(tmp_path)
    _add_job(conn, title="岗1", apply_end="2026-09-01")
    _add_job(conn, title="岗2", apply_end="2026-09-15")
    (e,) = _entries(conn)
    assert e["apply_end"] == "2026-09-15"


def test_start_never_after_end(tmp_path):
    """起点晚于终点是自相矛盾，宁可丢起点也不能发出去。"""
    conn = _mkdb(tmp_path)
    for i in range(4):
        _add_job(conn, title=f"岗位{i}", apply_end="2026-09-30", publish_at="2026-10-20")
    (e,) = _entries(conn)
    assert e["apply_end"] == "2026-09-30"
    assert e["apply_start"] is None


def test_single_publish_day_is_not_a_start(tmp_path):
    """一条补录职位的上架日（只占 1/5）不能冒充整批的网申开放日。"""
    conn = _mkdb(tmp_path)
    for i in range(5):
        _add_job(conn, title=f"岗位{i}", apply_end="2026-12-31",
                 publish_at="2026-10-25" if i == 0 else f"2026-09-0{i + 1}")
    (e,) = _entries(conn)
    assert e["apply_end"] == "2026-12-31"
    assert e["apply_start"] is None


def test_bulk_publish_day_becomes_start(tmp_path):
    conn = _mkdb(tmp_path)
    for i in range(4):
        _add_job(conn, title=f"岗位{i}", apply_end="2026-12-31", publish_at="2026-08-03")
    _add_job(conn, title="补录岗位", apply_end="2026-12-31", publish_at="2026-10-25")
    (e,) = _entries(conn)
    assert e["apply_start"] == "2026-08-03"
    assert e["apply_end"] == "2026-12-31"


def test_batch_published_on_deadline_day_is_not_a_start(tmp_path):
    """整批同一天上架、那天又是截止日 = 下架后批量补录，是终点不是起点。"""
    conn = _mkdb(tmp_path)
    for i in range(3):
        _add_job(conn, title=f"岗位{i}", apply_end="2026-10-20", publish_at="2026-10-20")
    (e,) = _entries(conn)
    assert e["apply_start"] is None
    assert e["apply_end"] == "2026-10-20"


def test_closed_jobs_do_not_backfill_auto_window(tmp_path):
    """已下架职位的截止日属于「那个批次关过窗」，不能给在招批次的窗口当值。"""
    conn = _mkdb(tmp_path)
    _add_job(conn, title="在招岗位", apply_end=None, publish_at=None)
    conn.execute("UPDATE job SET closed_at='2026-10-01' WHERE title='在招岗位'")
    _add_job(conn, title="新批次岗位", apply_end="2026-12-31")
    (e,) = _entries(conn)
    assert e["apply_end"] == "2026-12-31"
    assert e["open_jobs"] == 1
