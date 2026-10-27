"""人工条目从数据层「岗位级统计」补 grad_year / cities 的口径测试。

为什么需要这一步：日历 1,474 条里 grad_year 只有 44.5%、cities 只有 46.9%，
而数据层有 37k 校招岗位、34,866 条带城市。信息在同一个库里，产品里却看不到。
"""

import json
import sqlite3

import pytest

from jobradar.pipeline.calendar import fill_from_data_layer

AS_OF = "2026-10-26T14:00:00+08:00"


@pytest.fixture()
def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE company(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE job(id INTEGER PRIMARY KEY, company_id INT, recruit_type TEXT, grad_year INT,
                         cities TEXT, closed_at TEXT);
        INSERT INTO company(id,name) VALUES (1,'蔚来'),(2,'小鹏');
    """)
    return con


def add_jobs(con, cid, rtype, year, cities_list, n=1, closed=None):
    for _ in range(n):
        con.execute("INSERT INTO job(company_id,recruit_type,grad_year,cities,closed_at) VALUES (?,?,?,?,?)",
                    (cid, rtype, year, json.dumps(cities_list, ensure_ascii=False), closed))


def manual(**kw):
    base = {"id": "m1", "origin": "manual", "group_name": "蔚来", "company": "蔚来", "jd_company": "蔚来",
            "project_type": "秋招正式批", "grad_year": None, "cities": [],
            "source_type": "official_site", "source_name": "蔚来招聘官网", "source_url": "https://nio.com/campus",
            "source_date": "2026-08-01", "apply_url": "https://nio.com/campus"}
    base.update(kw)
    return base


def test_grad_year_filled_when_dominant(db):
    add_jobs(db, 1, "campus", 2027, ["上海"], n=5)
    rows = [manual()]
    assert fill_from_data_layer(rows, db, as_of=AS_OF) == 2          # 届次 + 城市
    assert rows[0]["grad_year"] == 2027
    assert rows[0]["cities"] == ["上海"]
    # 证据必须跟着改：值不是官网简章给的，来源就不能还写官网简章
    assert rows[0]["source_type"] == "data_layer"
    assert "campus" in rows[0]["source_name"]
    assert rows[0]["source_date"] == "2026-10-26"


def test_grad_year_not_filled_when_split(db):
    """两届岗位各占一半 -> 拿不准就不填，别把 2028 届的批次标成 2027。"""
    add_jobs(db, 1, "campus", 2027, ["上海"], n=5)
    add_jobs(db, 1, "campus", 2028, ["上海"], n=5)
    rows = [manual()]
    fill_from_data_layer(rows, db, as_of=AS_OF)
    assert rows[0]["grad_year"] is None
    assert rows[0]["cities"] == ["上海"]      # 城市仍然是确定的


def test_grad_year_needs_at_least_three_jobs(db):
    add_jobs(db, 1, "campus", 2027, ["上海"], n=2)
    rows = [manual()]
    fill_from_data_layer(rows, db, as_of=AS_OF)
    assert rows[0]["grad_year"] is None


def test_recruit_type_must_match(db):
    """只招社招的公司，不能把社招岗位的年份/城市灌进校招条目。"""
    add_jobs(db, 1, "social", 2027, ["北京"], n=9)
    rows = [manual()]
    assert fill_from_data_layer(rows, db, as_of=AS_OF) == 0
    assert rows[0]["cities"] == [] and rows[0]["grad_year"] is None


def test_closed_jobs_are_ignored(db):
    add_jobs(db, 1, "campus", 2027, ["上海"], n=9, closed="2026-09-01T00:00:00+08:00")
    rows = [manual()]
    assert fill_from_data_layer(rows, db, as_of=AS_OF) == 0


def test_single_occurrence_city_is_dropped(db):
    """只出现一次的城市多半是个别岗位，拿来当公司级城市会误导。"""
    add_jobs(db, 1, "campus", 2027, ["上海"], n=5)
    add_jobs(db, 1, "campus", 2027, ["拉萨"], n=1)
    rows = [manual()]
    fill_from_data_layer(rows, db, as_of=AS_OF)
    assert rows[0]["cities"] == ["上海"]


def test_existing_values_are_never_overwritten(db):
    add_jobs(db, 1, "campus", 2027, ["上海", "北京"], n=9)
    rows = [manual(grad_year=2028, cities=["合肥"])]
    assert fill_from_data_layer(rows, db, as_of=AS_OF) == 0
    assert rows[0]["grad_year"] == 2028 and rows[0]["cities"] == ["合肥"]
    assert rows[0]["source_name"] == "蔚来招聘官网"   # 没补任何字段 -> 来源也不动


def test_entry_without_linked_data_company_is_skipped(db):
    add_jobs(db, 1, "campus", 2027, ["上海"], n=9)
    rows = [manual(jd_company=None)]
    assert fill_from_data_layer(rows, db, as_of=AS_OF) == 0


def test_project_type_must_map_to_recruit_type(db):
    add_jobs(db, 1, "campus", 2027, ["上海"], n=9)
    rows = [manual(project_type="校园大使")]        # 属 campus，可以补
    fill_from_data_layer(rows, db, as_of=AS_OF)
    assert rows[0]["grad_year"] == 2027

    rows2 = [manual(project_type="无法识别的类型")]
    assert fill_from_data_layer(rows2, db, as_of=AS_OF) == 0


def test_cities_capped_at_ten(db):
    add_jobs(db, 1, "campus", 2027, [f"城市{i}" for i in range(20)], n=5)
    rows = [manual()]
    fill_from_data_layer(rows, db, as_of=AS_OF)
    assert len(rows[0]["cities"]) == 10
