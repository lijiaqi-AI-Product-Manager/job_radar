"""robots 合规检查的单元测试。

这个模块的存在理由就是「一天里两次抓了不该抓的页面」：radancy 欧莱雅 351 岗、
tupu360 共享域 774 岗，都是适配器跑通了、`opened` 数字很好看，但 robots 不允许。
所以这里的测试**不是**在测一个工具函数，是在锁住两条判断规则。
"""

import httpx
import pytest

from jobradar.robots import _path_variants, allows, check, source_urls

# 2026-10-26 原样抄下来的三份 robots
LOREAL = [
    "User-agent: *",
    "Disallow: /search-jobs",
    "Disallow: /en/search-jobs",
    "Disallow: /fr/recherche-d'offres",
    "Disallow: /location/",
    "Disallow: /category/",
    "Disallow: /employment/",
    "",
    "Sitemap: https://careers.loreal.com/sitemap.xml",
]
SANOFI = ["User-agent: *", "Disallow:/求职/"]
TUPU_SHARED = ["User-agent: *", "Disallow: /"]
SIEMENS = []   # robots.txt 是 404，无规则


@pytest.mark.parametrize("url", [
    "https://careers.loreal.com/search-jobs",
    "https://careers.loreal.com/en/search-jobs/China",
    "https://careers.loreal.com/en/location/china-mainland-jobs/3456/1814991/2/1",
    "https://careers.loreal.com/category/retail-jobs/3456/32362496/1",
])
def test_loreal_all_list_entries_blocked(url):
    """欧莱雅把**所有**列表入口都禁了。`/location/` 那条尤其要命：
    标准库 can_fetch 对 `/en/location/…` 返回 True，只看字面就会放行 351 个岗位。"""
    assert allows(LOREAL, url) is False


def test_loreal_detail_page_still_allowed():
    """详情页没被禁 —— 但这救不了它，因为挑不出「中国岗位」。"""
    assert allows(LOREAL, "https://careers.loreal.com/en/job/dubai/x/3456/1") is True


def test_language_segment_is_varianted():
    """`Disallow: /location/` 要能命中 `/en/location/…`，靠的是去语言段的保守匹配。"""
    assert _path_variants("/en/location/x") == ["/en/location/x", "/location/x"]
    assert _path_variants("/location/x") == ["/location/x"]
    # 不是语言段的段不能被剥掉
    assert _path_variants("/jobs/location/x") == ["/jobs/location/x"]


def test_shared_host_disallow_all():
    assert allows(TUPU_SHARED, "https://careersite.tupu360.com/iqvia/position/index") is False
    assert allows(TUPU_SHARED, "https://careersite.tupu360.com/") is False


def test_sanofi_only_chinese_detail_blocked():
    assert allows(SANOFI, "https://jobs.sanofi.cn/search-jobs") is True
    assert allows(SANOFI, "https://jobs.sanofi.cn/求职/北京/x/3036/1") is False


def test_empty_robots_allows_everything():
    assert allows(SIEMENS, "https://jobs.siemens.com.cn/siemens/position/index") is True


def test_allow_overrides_shorter_disallow():
    """robots 规范：最长匹配优先，同长时 allow 优先。"""
    rules = ["User-agent: *", "Disallow: /a/", "Allow: /a/b/"]
    assert allows(rules, "https://x.com/a/c") is False
    assert allows(rules, "https://x.com/a/b/c") is True


def test_other_agent_rules_do_not_apply():
    rules = ["User-agent: badbot", "Disallow: /", "", "User-agent: *", "Disallow: /private/"]
    assert allows(rules, "https://x.com/public") is True
    assert allows(rules, "https://x.com/private/x") is False


def test_comments_and_blank_lines():
    rules = ["# 注释", "User-agent: *", "Disallow: /x/   # 行尾注释", ""]
    assert allows(rules, "https://x.com/x/1") is False
    assert allows(rules, "https://x.com/y") is True


@pytest.mark.parametrize("params,adapter,expect_first", [
    ({"tenant": "boe"}, "beisen", "https://boe.zhiye.com/api/Jobad/GetJobAdPageList"),
    ({"base": "https://jobs.siemens.com.cn", "tenant": "siemens"}, "tupu360",
     "https://jobs.siemens.com.cn/siemens/position/index"),
    ({"base": "https://jobs.sanofi.cn", "lang": "", "country": ""}, "radancy",
     "https://jobs.sanofi.cn/search-jobs"),
    ({"host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia"}, "workday",
     "https://nvidia.wd5.myworkdayjobs.com/"),
    ({"tenant": "SU66f3c75a6202cc1a0cba3202", "host": "ausnutria.hotjob.cn"}, "hotjob",
     "https://ausnutria.hotjob.cn/"),
    ({}, "alibaba", "https://campus-talent.alibaba.com/"),
])
def test_source_urls(params, adapter, expect_first):
    urls = source_urls(params, adapter)
    assert urls and urls[0] == expect_first


def test_tenant_is_not_prepended_to_host():
    """只有北森把 tenant 当主机前缀。workday/hotjob 的 host 已经是完整域名，
    再拼一次会得到 `nvidia.nvidia.wd5...` 这种不存在的域名 —— 检查它等于没检查。"""
    urls = source_urls({"host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia"}, "workday")
    assert all("nvidia.nvidia" not in u for u in urls)
    assert all(".zhiye.com" not in u for u in urls)


def test_unknown_source_returns_empty():
    """推断不出来就返回空，CLI 标 UNKNOWN。检查一个错域名得出的「允许」比不检查更危险。"""
    assert source_urls({}, "some_unknown_adapter") == []


@pytest.mark.parametrize("status,body,content_type", [
    (429, "slow down", "text/plain"),
    (500, "server error", "text/plain"),
    (200, '<html><script>captcha()</script></html>', "text/html"),
    (200, '<textarea id="renderData">challenge</textarea>', "text/plain"),
])
def test_hard_failures_and_challenges_never_mean_permission(status, body, content_type):
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text=body, headers={"content-type": content_type})))
    verdict = check(client, "https://example.com/jobs")
    assert not verdict.allowed and verdict.host_robots == "unreachable"
    client.close()


def test_network_failure_does_not_grant_robots_permission():
    def fail(request):
        raise httpx.ConnectTimeout("offline", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        assert check(client, "https://example.com/jobs").allowed is False


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_robots_client_error_follows_rfc9309_unavailable_policy(status):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as client:
        verdict = check(client, "https://example.com/jobs")
    assert verdict.allowed
    assert verdict.host_robots == ("absent" if status in (404, 410) else "unavailable")


def test_multiple_user_agents_in_one_group_are_honored():
    rules = ["User-agent: *", "User-agent: otherbot", "Disallow: /private/"]
    assert not allows(rules, "https://example.com/private/job")


def test_wildcard_and_end_anchor_rules_are_not_ignored():
    rules = ["User-agent: *", "Disallow: /*/private/*", "Disallow: /*.pdf$", "Allow: /public/allowed.pdf$"]
    assert not allows(rules, "https://example.com/en/private/jobs")
    assert not allows(rules, "https://example.com/manual.pdf")
    assert allows(rules, "https://example.com/public/allowed.pdf")
    assert allows(rules, "https://example.com/manual.pdf/extra")
