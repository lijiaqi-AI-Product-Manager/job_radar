import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "coverage_report", Path(__file__).parent.parent / "scripts" / "coverage_report.py")
cov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cov)


def test_targets_file_is_consistent():
    t = cov.load_targets()
    names = [n for ns in t["sectors"].values() for n in ns]
    assert len(names) == len(set(names)), "目标公司重复"
    assert len(names) >= 200
    for key in [*(t.get("aliases") or {}), *(t.get("blocked") or {})]:
        assert key in names, f"{key} 不在 sectors 中"


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
