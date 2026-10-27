"""`calendar_extract` 的日期构造与窗口抽取：不允许产生「不存在的日期」。

这条测试是补一个真实事故（2026-10-26）：`_d()` 只校验 `1 <= d <= 31`，
于是「2025年11月00日」这种页面上的占位写法被构造成 `2025-11-00` 写进
`calendar/entries/hongqingting.yaml`，随后 `ManualEntry` 校验抛
`day is out of range for month`，整个 `calendar-build` 直接失败——
一条脏数据让 1323 条日历全部生成不出来。

所以这里锁两件事：
  1. `_d()` 用真日历校验，返回的日期一定能被 `date.fromisoformat` 接受；
  2. `extract_window()` 遇到这种日期返回空，而不是把它吐出去。
"""

from datetime import date

import pytest

from jobradar.pipeline.calendar_extract import _d, extract_window


@pytest.mark.parametrize("args", [
    (2025, 11, 0),     # 月写对了、日写成 00（页面占位写法）
    (2025, 2, 30),     # 2 月没有 30 号
    (2025, 4, 31),     # 4 月没有 31 号
    (2026, 13, 1),     # 月份越界
    (1999, 10, 1),     # 年份越界
    (2041, 10, 1),
])
def test_d_rejects_impossible_dates(args):
    assert _d(*args) is None


@pytest.mark.parametrize("args,expected", [
    ((2026, 10, 26), "2026-10-26"),
    ((2028, 2, 29), "2028-02-29"),   # 闰年 2 月 29 日是合法日期
])
def test_d_accepts_real_dates(args, expected):
    assert _d(*args) == expected
    date.fromisoformat(expected)     # 必须能被标准库接受


def test_d_output_always_parses():
    """穷举十来年的每一天，保证 `_d` 的输出永远能被 fromisoformat 接受。"""
    for y in (2024, 2025, 2026):
        for m in range(1, 13):
            for d in range(0, 32):
                v = _d(y, m, d)
                if v is not None:
                    date.fromisoformat(v)


def test_window_ignores_placeholder_day_zero():
    r = extract_window("网申截止时间：2025年11月00日")
    assert r["end"] is None
    assert r["start"] is None


def test_window_keeps_a_real_deadline():
    r = extract_window("网申截止时间：2026年11月30日")
    assert r["end"] == "2026-11-30"
