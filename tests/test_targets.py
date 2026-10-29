import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "coverage_report", Path(__file__).parent.parent / "scripts" / "coverage_report.py")
cov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cov)


def test_targets_file_is_consistent():
    t = cov.load_targets()
    names = [n for ns in t["sectors"].values() for n in ns]
    assert len(names) == len(set(names)), "行业清单内目标公司重复"
    prov = t.get("provinces") or {}
    assert prov, "缺少省域目标清单"
    for p, ns in prov.items():
        assert len(ns) == len(set(ns)), f"{p} 省内目标重复"
    # 同一家公司可以同时在行业清单和省域清单里（只算一次目标），但总数要够到「1500 家」阶段目标
    assert len(set(names) | {n for ns in prov.values() for n in ns}) >= 1500
    all_names = set(names) | {n for ns in prov.values() for n in ns}
    for key in [*(t.get("aliases") or {}), *(t.get("blocked") or {})]:
        assert key in all_names, f"{key} 不在目标清单中"


def test_target_names_counts_cross_section_company_once():
    """腾讯既是互联网目标也是广东重点企业：匹配结果只能有一份，不能算两次。"""
    from jobradar.pipeline.calendar import target_names

    t = {"sectors": {"互联网": ["腾讯"]}, "provinces": {"广东": ["腾讯", "华为"]}}
    names = [n for n, _ in target_names(t)]
    assert names == ["腾讯", "华为"]
    assert dict(target_names(t))["华为"] == "省域·广东"


def test_match_uses_aliases_and_substrings():
    t = {"sectors": {"x": ["中核集团", "腾讯", "美团", "百度"]}, "aliases": {"中核集团": ["中国核工业集团"]},
         "blocked": {"百度": "no-auth"}}
    m = cov.match(t, {"中国核工业集团", "腾讯", "美团点评"})
    assert m == {"中核集团": ["中国核工业集团"], "腾讯": ["腾讯"], "美团": ["美团点评"], "百度": []}
    report = cov.render(t, m, {"腾讯": 3})
    assert "已覆盖 **3**" in report and "腾讯（3）" in report and "百度：no-auth" in report


def test_blocked_company_is_not_counted_as_covered():
    """「京东」会被子串匹配到「京东方」，但 blocked 的公司不能算已覆盖。"""
    t = {"sectors": {"x": ["京东", "京东方", "腾讯"]}, "blocked": {"京东": "验证码"}}
    m = cov.match(t, {"京东方", "腾讯"})
    report = cov.render(t, m)
    assert "已覆盖 **2**" in report
    assert "- **x**：京东方、腾讯" in report        # 已覆盖列表里没有京东
    assert "- 京东：验证码" in report
    assert "待侦察 0" in report                     # 京东方/腾讯已覆盖，京东在 blocked


def test_industry_targets_pool_is_consistent():
    """行业细分池：365 行、别名只能指向池内公司、同一行里不重复。"""
    ind = cov.load_industries(Path(__file__).parent.parent / "targets" / "industry_targets.yaml")
    assert sum(len(rows) for rows in ind.values()) == 365
    names = {str(c) for rows in ind.values() for cs in rows.values() for c in cs}
    for sec, rows in ind.items():
        for line, cs in rows.items():
            assert len(cs) == len({str(c) for c in cs}), f"{sec}/{line} 代表企业重复"
    aliases = cov.load_industry_aliases()
    assert aliases, "行业池别名表为空"
    for key in aliases:
        assert key in names, f"{key} 不在行业池里"
