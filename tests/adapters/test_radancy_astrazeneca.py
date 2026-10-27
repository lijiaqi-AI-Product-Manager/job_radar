"""Radancy 形态 D：阿斯利康中国站 `job-search.astrazeneca.cn`。

与赛诺菲（形态 B）的三处实质差异，任何一处退回单一实现都会红：
1. 卡片 `<a>` 里先有 `<div class="brand-logo-wrapper"><img></div>`，标题 `<h2>` 不在 `<a>` 后紧跟的位置
   —— 旧正则 `>\\s*<h2>` 在这里一条都匹配不到（2026-10-26 实测 0/15）。
2. 正文在 `<section class="job-description">` 里的 `<div class="ats-description">`，
   但正文前面夹了整个 `details-and-apply-button` 工具栏，形态 C 的 `\\s*` 跨不过去。
3. 日期是 `07/07/2026`（MM/DD/YYYY），不是赛诺菲的 `Oct. 26, 2026`。
"""

from pathlib import Path

import yaml

from jobradar.adapters.base import make_client
from jobradar.adapters.radancy import RadancyAdapter, _cities, _city_from_url, _en_date
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "radancy_radancy-astrazeneca"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    # 必须用 make_client：follow_redirects=True 是抓取行为的一部分（站点首页 302 到筛选后的 URL），
    # 用裸 httpx.Client 回放会停在 302 上
    a = RadancyAdapter(source(**params), make_client(ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_brand_logo_card_is_parsed():
    """卡片里夹了 logo div 也要能取到标题 —— 这是 `>\\s*<h` 那个坑。"""
    jobs = run(max_pages=1)
    assert len(jobs) == 15
    assert all(j.title.strip() for j in jobs)


def test_jd_body_is_extracted_past_the_toolbar():
    """正文在工具栏 div 之后，`\\s*` 跨不过去；解出来的正文必须是完整长文而不是工具栏文字。"""
    jobs = run(max_pages=1)
    detailed = [j for j in jobs if j.description]
    assert len(detailed) == 3, "fixtures 只录了 3 个详情响应"
    assert all(len(j.description) > 500 for j in detailed)
    assert not any("立即申请" in j.description[:40] for j in detailed)


def test_us_date_format_is_parsed():
    """`07/07/2026` 是 MM/DD/YYYY（站点 DisplayJobDateFormat="MMM. dd, yyyy" 的欧式变体）。"""
    assert _en_date("07/07/2026") == "2026-07-07"
    assert _en_date("12/31/2026") == "2026-12-31"
    assert _en_date("2026-10-26") == "2026-10-26"
    assert _en_date("Oct. 26, 2026") == "2026-10-26"
    # 赛诺菲个别岗位把 MMM. 本地化成中文月份（2026-10-26 实测 75 条里有 1 条）
    assert _en_date("发布于 \xa0 10月. 25, 2026") == "2026-10-25"
    assert _en_date("11月. 30, 2026") == "2026-11-30"
    # 非法月份要拒，不能给出 2026-13-25 这种"看起来像日期"的值
    assert _en_date("13月. 25, 2026") is None
    assert _en_date("not a date") is None


def test_province_city_pair_keeps_only_the_city():
    """地点是「省 市」用空格分隔：「江苏 无锡」→ 无锡，不能把省也塞进城市字段。"""
    assert _cities("上海 上海") == ["上海"]
    assert _cities("江苏 无锡") == ["无锡"]
    assert _cities("浙江 杭州") == ["杭州"]
    # 只剩省（没有市）时得留着，那是唯一地区信息
    assert _cities("江苏") == ["江苏"]
    # 英文串不能被空格规则误拆
    assert _cities("Shanghai, Shanghai Municipality, China Mainland") == ["上海"]


def test_placeholder_location_falls_back_to_url():
    """列表写「Multiple locations」时 `_cities` 必须返回空，才能触发 URL 兜底。

    2026-10-26 全量实测：阿斯利康 29/279 条列表地点是占位词，真值只在 URL 路径段
    `/工作/上海/slug/12977/94245123536`。若 `_cities("Multiple locations")` 返回
    `["Multiple locations"]`，`_cities(...) or _city_from_url(...)` 的短路就不会走兜底，
    城市覆盖率会从 99.6% 掉到 89.6%。
    """
    for raw in ("Multiple locations", " Multiple locations ", "multiple locations"):
        assert _cities(raw) == [], raw
    assert _city_from_url("https://job-search.astrazeneca.cn/%e5%b7%a5%e4%bd%9c/"
                          "%e4%b8%8a%e6%b5%b7/x/12977/94245123536") == ["上海"]
    # 路径段是全小写英文小城时也不能丢（赛诺菲 Verna）
    assert _city_from_url("https://jobs.sanofi.cn/%e5%b7%a5%e4%bd%9c/verna/x/3036/1") == ["verna"]
    # 「中国」这种非地名段不能当城市
    assert _city_from_url("https://jobs.sanofi.cn/%e5%b7%a5%e4%bd%9c/"
                          "%e4%b8%ad%e5%9b%bd/x/3036/1") == []


def test_placeholder_and_lowercase_inputs_do_not_raise():
    """全小写地名（省掉大小写分支）和占位词混在一条串里时不能抛 UnboundLocalError。

    2026-10-26 实测：`_cities()` 的 `found` 变量没在每轮重置，`city_from_english("verna")`
    返回 None 后三个 elif 全不命中，直接 NameError/UnboundLocalError。
    """
    assert _cities("verna") == ["verna"]
    assert _cities("Multiple locations, 上海") == ["上海"]
    assert _cities("中国") == []


def test_publish_date_present_on_every_job_with_detail():
    jobs = run(max_pages=1)
    detailed = [j for j in jobs if j.description]
    assert all(j.publish_at for j in detailed)
    assert all(len(j.publish_at) == 10 for j in detailed)
