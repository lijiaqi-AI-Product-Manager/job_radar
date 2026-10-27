"""人工条目 <-> 数据层公司的兜底匹配（`match_entry_company`）。

2026-10-26 实测的背景：日历 1,474 条人工条目里 **1,150 条** 的 `jd_company` 是空的，
因为它们不在 targets.yaml 的目标清单里；其中 **74 条** 的公司名与数据层公司名逐字相等。
"""

from jobradar.pipeline.calendar import ManualEntry, match_entry_company


def entry(**kw):
    base = {"id": "x", "group": "某集团", "project_type": "校招", "as_of": "2026-10-26",
            "source": {"type": "official_site", "name": "官网", "url": "https://e.com"},
            "apply_url": "https://e.com/apply"}
    base.update(kw)
    return ManualEntry(**base)


DATA = {"爱尔眼科", "阿里云", "AMD", "AMD 中国", "华为", "华为海洋", "京东", "京东方", "蔚来", "蔚来汽车"}


def test_exact_company_name_wins():
    assert match_entry_company(entry(company="爱尔眼科"), DATA) == ["爱尔眼科"]


def test_group_name_is_also_a_candidate():
    assert match_entry_company(entry(group="阿里云"), DATA) == ["阿里云"]


def test_two_char_name_does_not_steal_a_longer_company():
    """「华为」不能把「华为海洋」认领走——那是另一家公司。"""
    assert match_entry_company(entry(company="华为"), DATA) == ["华为"]
    assert "华为海洋" not in match_entry_company(entry(company="华为"), DATA)


def test_exact_match_beats_substring():
    """「京东」精确命中自己，不会因为子串把「京东方」也拉进来（2026-10-22 踩过的坑）。"""
    assert match_entry_company(entry(company="京东"), DATA) == ["京东"]
    assert match_entry_company(entry(company="京东方"), DATA) == ["京东方"]


def test_long_name_falls_back_to_containment():
    # "蔚来汽车" 与数据层 "蔚来"：精确匹配命中自己
    assert match_entry_company(entry(company="蔚来汽车"), DATA) == ["蔚来汽车"]
    # "上海蔚来汽车" 含 "蔚来汽车"(4 字，收) 与 "蔚来"(2 字，太短不收) ——
    # 判的是"被包含的一方多长"，不是"两个词谁短"，否则 "蔚来汽车" 也会被一起误杀
    assert match_entry_company(entry(company="上海蔚来汽车"), DATA) == ["蔚来汽车"]


def test_no_match_returns_empty():
    assert match_entry_company(entry(company="不存在的公司"), DATA) == []


def test_empty_entry_returns_empty():
    assert match_entry_company(entry(company=None, product=None, group=""), DATA) == []


def test_product_is_considered():
    assert match_entry_company(entry(company=None, product="阿里云"), DATA) == ["阿里云"]
