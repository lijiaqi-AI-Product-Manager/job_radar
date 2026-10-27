"""Avature 适配器契约测试（达能 careers.danone.com.cn）。

两条必须守住的线：
1. **只抓 JobDetail 数字尾**。sitemap 里混着 `/careers/Login`、`/careers/Error`、
   `/careers/AgentCreate` 这些账户页，匿名访问一律 403 —— 漏一个就会让整轮抓取崩掉
   （2026-10-26 实测：73 条有效岗位全丢，只因为多请求了一个 `/careers/Error`）。
2. 地点靠 icon class（`banner--field--icon-location`）定位，不靠位置猜；
   日期在 `og:description` 旁边的 `meta Description` 里，格式是 `21-Oct-2026`。
"""

import re
from pathlib import Path

import yaml

from jobradar.adapters.avature import (
    DEFAULT_PATH_RE,
    G_DATE,
    G_TITLE,
    GLOBAL_PATH_RE,
    AvatureAdapter,
    _d_mon_yyyy,
    _dd_mon_yyyy,
    _g_attrs,
    _global_cities,
    _text,
)
from jobradar.adapters.base import make_client
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "avature_avature-danone"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = AvatureAdapter(source(**params), make_client(ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_account_pages_are_filtered_out():
    """`/careers/Error` / `/careers/Login` 不能进 URL 列表 —— 它们匿名访问 403。"""
    p = re.compile(DEFAULT_PATH_RE)
    assert p.search("https://careers.danone.com.cn/zh_CN/careers/JobDetail/10300")
    assert p.search("https://careers.danone.com.cn/zh_CN/careers/JobDetail/Project-Manager-IPRO/10283")
    for bad in ("Error", "Login", "AgentCreate", "RegistrationMethods", "ProfileEdit", "SearchJobs"):
        assert not p.search(f"https://careers.danone.com.cn/zh_CN/careers/{bad}"), bad
    # 带 slug 但没有数字尾的也不是岗位页
    assert not p.search("https://careers.danone.com.cn/zh_CN/careers/JobDetail/some-slug")


def test_only_the_recorded_details_are_returned():
    """fixtures 只留了 2 个详情响应（`--keep-details 2`），回放只该产出 2 条。"""
    jobs = run(max_pages=1)
    assert len(jobs) == 2


def test_field_mapping():
    jobs = run(max_pages=1)
    job = jobs[0]
    assert job.company == "达能"
    assert job.source_job_id.isdigit()
    assert job.url.startswith("https://careers.danone.com.cn/zh_CN/careers/JobDetail/")
    assert job.title.strip()
    assert job.cities, "地点从 icon-location 的 banner--field 里取"
    assert job.publish_at and re.fullmatch(r"\d{4}-\d{2}-\d{2}", job.publish_at)
    assert job.department, "职能来自 banner__text__subtitle"
    assert job.description and len(job.description) > 300


def test_dd_mon_yyyy_date():
    """`21-Oct-2026` 是 Avature 的 meta Description 格式；认不出月份就返回 None 而不是瞎猜。"""
    assert _dd_mon_yyyy("21-Oct-2026") == "2026-10-21"
    assert _dd_mon_yyyy("01-Jan-2027") == "2027-01-01"
    assert _dd_mon_yyyy("31-Dec-2026") == "2026-12-31"
    assert _dd_mon_yyyy("21-Xxx-2026") is None
    assert _dd_mon_yyyy("2026-10-21") is None
    assert _dd_mon_yyyy(None) is None


# ---- 版式 B：达能全球站 `careers.danone.com/en-global/jobs/…` ----
# 同一套 Avature 后台，但走 AEM 渲染：字段挂在 <article> 的属性上，日期是 `Posted: 22 Oct 2026`。


def test_global_path_re_only_matches_job_pages():
    """全球站 sitemap 里 835 个 loc，只有 `-<id>-<lang>.html` 结尾的是岗位。

    页面类 URL（`/jobs/html`、`/stories/...`、`/about-us.html`）不能进 ——
    它们没有 country/city 属性，抽出来是空壳岗位。
    """
    p = re.compile(GLOBAL_PATH_RE)
    assert p.search("https://careers.danone.com/en-global/jobs/"
                    "digitalization-automation-specialist-25905-en-us.html")
    # slug 很长、带 `china-w-m` 这种段也要能匹配（正则只锚「-数字-语言.html」结尾）
    assert p.search("https://careers.danone.com/en-global/jobs/"
                    "vie-junior-business-development-manager-afh-china-w-m-28163-en-us.html")
    for bad in ("https://careers.danone.com/en-global/jobs/html",
                "https://careers.danone.com/en-global/stories/foo.html",
                "https://careers.danone.com/en-global/about-us.html"):
        assert not p.search(bad), bad


def test_global_date_format():
    """版式 B 的日期在 `dn-jobdetails__posteddate` 里，格式 `Posted: 22 Oct 2026`。

    和版式 A 的 `21-Oct-2026` 不是一回事：月名是全称/缩写 + 空格，还带 "Posted: " 前缀。
    共用同一个解析器就会把两种格式都解析成 None。
    """
    assert _d_mon_yyyy("Posted: 22 Oct 2026") == "2026-10-22"
    assert _d_mon_yyyy("Posted: 1 September 2026") == "2026-09-01"
    assert _d_mon_yyyy("Posted: 31 Dec 2026") == "2026-12-31"
    assert _d_mon_yyyy("no date here") is None
    assert _d_mon_yyyy(None) is None


def test_global_cities_keep_english_when_unmapped():
    """全球站的城市是英文。能映射成中文的映射，映射不到的要**保留原文**。

    `city_from_english` 只收中国城市，`Kuala Lumpur` / `Paris` 查不到 ——
    这时丢空等于把「这条岗位在哪个国家」整个抹掉。
    """
    assert _global_cities("Shanghai") == ["上海"]
    assert _global_cities("Kuala Lumpur") == ["Kuala Lumpur"]
    assert _global_cities("Paris") == ["Paris"]
    assert _global_cities("") == []


def test_global_layout_parses_article_attributes():
    """`<article country=… city=… positionType=… description=…>` 是版式 B 的全部字段来源。

    fixtures 录的是**版式 A**（中国站），所以这里用内联 HTML 验抽取逻辑，
    不依赖网络也不依赖额外的 fixture 目录。
    """
    detail = (
        '<div class="cmp-job-header"><div class="dn-jobdetails__meta">'
        '<div class="dn-jobdetails__meta-tag"><h1>Data</h1></div>'   # 面包屑，不能当标题
        '<div class="dn-jobdetails__meta-head"><h1>Digitalization &amp; Automation Specialist</h1></div>'
        '<ul class="dn-jobdetails__meta-details"><li><span class="dn-jobdetails__posteddate">'
        'Posted: 22 Oct 2026</span></li></ul></div></div>'
        '<article class="cmp-contentfragment  cmp-contentfragment--en_US" '
        'country="Malaysia" city="Kuala Lumpur" positionType="Permanent Full-Time" '
        'description="&lt;ul>&lt;li>At least 2 years in BI&lt;/li>&lt;/ul>"></article>'
    )
    attrs = _g_attrs(detail)
    assert attrs["country"] == "Malaysia"
    assert attrs["city"] == "Kuala Lumpur"
    # description 是转义过的，必须 unescape 后才是 HTML
    assert attrs["description"].startswith("<ul><li>At least 2 years in BI")
    t = G_TITLE.search(detail)
    assert t and _text(t.group("t")) == "Digitalization & Automation Specialist"
    assert _d_mon_yyyy(G_DATE.search(detail).group("v")) == "2026-10-22"
