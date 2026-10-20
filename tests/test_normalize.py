import pytest

from jobradar.normalize import (
    batch_from_text,
    cities_from_text,
    cities_from_title,
    grad_year_from_text,
)


@pytest.mark.parametrize("text,year", [
    ("【27校招】人力管培生(J15003)", 2027),
    ("审计员（2027届校招-北京分所）(J10667)", 2027),
    ("硬件工程师（27届校招）", 2027),
    ("算法工程师岗-AI机器视觉（2027校招）", 2027),
    ("2028届暑期实习-前端开发", 2028),
    ("27届校招-AI平台研发工程师(J19213)", 2027),
    ("【2026届春招】测试工程师", 2026),
    ("销售总监/经理（CBG/全国）(J13700)", None),
    ("3A动作冒险游戏-战斗主策划", None),
    ("工作经验2027年以上", None),   # 不是届别
    ("J12027 后端开发", None),     # 编号里的数字不算
    ("【2027】研究助理岗(J19663)", 2027),
    ("【2027】云控制台开发工程师（AI架构）-成都(J14240)", 2027),
    ("（2027届校招）财富管理培训生", 2027),
    ("项目经理（2027）", None),     # 括号里只有年份但不在开头的方括号里，不算
    ("【27年校招】AI战略与产品运营管培生(J14975)", 2027),
])
def test_grad_year(text, year):
    assert grad_year_from_text(text) == year


@pytest.mark.parametrize("text,year", [
    ("射频IC工程师-上海-2027(J11703)", 2027),
    ("2027-数字IC后端工程师-上海(J10312)", 2027),
    ("项目经理（2027）", 2027),
    ("工程师（3年以上经验，2027年以上不招）", None),
    ("J12027 后端开发", None),
    ("后端开发工程师", None),
])
def test_grad_year_loose_for_campus_titles(text, year):
    """校招/实习标题中独立出现的年份即届别（宽松模式只用于 campus/intern）。"""
    assert grad_year_from_text(text, loose=True) == year


@pytest.mark.parametrize("text,batch", [
    ("【2027届提前批】算法工程师", "提前批"),
    ("2027届秋招正式批-产品经理", "正式批"),
    ("【补录】硬件工程师", "补录"),
    ("2026届春招-运营", "春招"),
    ("2027秋季校园招聘 销售工程师", "秋招"),
    ("2027秋招 销售", "秋招"),
    ("后端开发工程师", None),
])
def test_batch(text, batch):
    assert batch_from_text(text) == batch


def test_none_and_empty():
    assert grad_year_from_text(None) is None and batch_from_text("") is None


@pytest.mark.parametrize("text,cities", [
    ("北京市", ["北京"]),
    ("江苏省-连云港市", ["连云港"]),
    ("深圳", ["深圳"]),
    ("上海市,北京市", ["上海", "北京"]),
    ("广东省·深圳市", ["深圳"]),
    ("海外", ["海外"]),
    ("", []),
    (None, []),
    ("北京市,北京市", ["北京"]),
    ("北京市-海淀区", ["北京"]),       # 有"市"一级时取市，不取区
    ("浙江省-杭州市-余杭区", ["杭州"]),
    ("上海市-浦东新区,江苏省-苏州市", ["上海", "苏州"]),
])
def test_cities(text, cities):
    assert cities_from_text(text) == cities


@pytest.mark.parametrize("title,cities", [
    ("验证工程师-深圳-2027(J11700)", ["深圳"]),
    ("临床医师（武汉）(J14957)", ["武汉"]),
    ("设备员-青岛(J34014)", ["青岛"]),
    ("数字IC后端工程师(base武汉/大连/苏州/西安/珠海/成都-27届校招)(J12716)", ["武汉", "大连", "苏州", "西安", "珠海", "成都"]),
    ("2027-数字IC后端工程师-上海(J10312)", ["上海"]),
    ("北京大学合作项目专员", []),          # 不在分隔符之间，不算
    ("深圳湾实验室研究员", []),
    ("后端开发工程师", []),
])
def test_cities_from_title(title, cities):
    assert cities_from_title(title) == cities
