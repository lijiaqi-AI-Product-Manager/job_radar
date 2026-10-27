from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.beisen import BeisenAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "beisen"


def source(**kw):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data.update(kw)
    return SourceConfig(**data)


def run(src=None):
    a = BeisenAdapter(src or source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def by_title(jobs, title):
    return next(j for j in jobs if j.title == title)


def test_two_pages_are_fetched():
    jobs = run()
    assert len(jobs) == 40
    assert len({j.id for j in jobs}) == 40


def test_campus_record_mapping():
    j = by_title(run(), "【27校招】人力管培生(J15003)")
    assert j.id == "beisen-fosunpharma:f4e9186a-6a1c-422f-a226-9ab168987881"
    assert j.company == "复星医药"
    assert j.recruit_type == "campus"
    assert j.grad_year == 2027
    assert j.url == "https://fosunpharma.zhiye.com/campus/detail?jobAdId=f4e9186a-6a1c-422f-a226-9ab168987881"
    assert j.description.startswith("1、参与招聘全流程")
    assert j.requirements.startswith("1、本科及以上应届生或毕业2年内")
    # 2026-10-26 起列表接口带 DisplayFields 就能拿到 `LocNames: ['广西壮族自治区·桂林市']`
    assert j.cities == ["桂林"]
    assert j.publish_at == "2026-10-12"
    # `EndTime` 是哨兵 `2222-02-02`（长期有效），不能当成真实截止日
    assert j.apply_end is None


def test_social_record_mapping():
    j = by_title(run(), "品牌传播高级总监(J13868)")
    assert j.recruit_type == "social"
    assert j.grad_year is None and j.batch is None
    assert "/social/detail?jobAdId=" in j.url


def test_type_mix_matches_category_ids():
    """条数随复星门户当期岗位浮动，这里只断言「两种类型都在，且总数为 40」。

    原来写死 `campus == 33 / social == 7` 是 2026-10-20 录制时的快照；10-26 重录后是 31/9。
    写死当期业务数字的测试每年都会红一次，而它想守的是「CategoryId 分流正确」这件事。
    """
    jobs = run()
    campus = sum(j.recruit_type == "campus" for j in jobs)
    social = sum(j.recruit_type == "social" for j in jobs)
    assert campus + social == len(jobs) == 40
    assert campus > 0 and social > 0


def test_display_fields_fetch_cities_and_dates():
    """不带 `DisplayFields` 时 `LocNames` 恒空、`PostDate` 恒 `0001-01-01`。
    这条是防回归：谁把请求体里的 `DisplayFields` 删掉，城市会静默归零（125,507 条岗位的教训）。"""
    jobs = run()
    assert sum(1 for j in jobs if j.cities) == 40
    assert sum(1 for j in jobs if j.publish_at) == 40
    for j in jobs:
        assert j.apply_end != "2222-02-02", "长期有效的哨兵日期不能落库"


def test_recruit_types_filter():
    jobs = run(source(recruit_types=["campus"]))
    assert {j.recruit_type for j in jobs} == {"campus"}


def test_unknown_category_and_missing_fields_are_skipped():
    a = BeisenAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({"Id": "x", "JobAdName": "t", "CategoryId": "99"},
                {"Id": "", "JobAdName": "t", "CategoryId": "2"},
                {"Id": "x", "JobAdName": "", "CategoryId": "2"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)


@pytest.mark.parametrize("cat,want", [
    ("4", "social"),   # 优衣库「官网旗舰店担当」
    ("6", "intern"),   # 优衣库「非全日制…」兼职
    ("8", "social"),   # 茶颜悦色「茶颜-门店全职-启东」
    ("9", "intern"),   # 「门店运营学生用工」
    ("14", "intern"),  # 「茶颜-门店兼职-宜章县」
])
def test_tenant_self_configured_categories(cat, want):
    """CategoryId 是**租户自己配的**，不是平台规范：茶颜悦色把门店岗全挂在 8/9/11~14 上，
    映射表里没有就被整条丢弃——`crawl --only beisen-cyys` 曾经 1426 岗抓 0 条，
    看着像反爬，其实一行映射缺口。这条防的就是「新增租户又用了新编号」时静默归零。"""
    a = BeisenAdapter(source(), httpx.Client(), sleep=lambda s: None)
    j = a.normalize({"Id": f"u{cat}", "JobAdName": "门店运营全职", "CategoryId": cat})
    assert j.recruit_type == want
    assert f"/{want}/detail?jobAdId=u{cat}" in j.url


def test_category_5_is_social():
    """CategoryId=5：实测长鑫、中国人寿的"专家/经理/资深"类岗位，门户导航中为第二个社招页面。"""
    a = BeisenAdapter(source(), httpx.Client(), sleep=lambda s: None)
    j = a.normalize({"Id": "u5", "JobAdName": "设计验证经理-Design Verification Manager(J21397)", "CategoryId": "5"})
    assert j.recruit_type == "social" and "/social/detail?jobAdId=u5" in j.url


def test_intern_mapping():
    a = BeisenAdapter(source(), httpx.Client(), sleep=lambda s: None)
    j = a.normalize({"Id": "u1", "JobAdName": "2028届暑期实习-AI数智", "CategoryId": "3"})
    assert (j.recruit_type, j.grad_year) == ("intern", 2028)
    assert "/intern/detail?jobAdId=u1" in j.url


def test_api_error_raises():
    def handler(request):
        return httpx.Response(200, json={"Code": 500, "Message": "boom"})

    a = BeisenAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        list(a.fetch_all())


# ---- 2026-10-26 补：列表接口里的日期与占位 JD ----

def test_post_date_and_end_time_are_mapped():
    """列表接口本来就给 `PostDate` / `EndTime`，之前整个被丢掉。

    全项目 publish_at 覆盖率只有 1.2%，北森这 400 个源是最大的一块缺口 —— 数据一直在，
    只是没取。`0001-01-01T00:00:00` 是「未填」哨兵，必须落成 None 而不是 0001-01-01。
    """
    from jobradar.adapters.beisen import BeisenAdapter

    raw = {
        "Id": "x-1", "JobAdName": "后端工程师(J1)", "CategoryId": "1",
        "LocNames": ["上海"], "Duty": "负责服务端开发与维护，参与架构设计。",
        "Require": "三年以上后端开发经验，熟悉 Python。",
        "PostDate": "2026-09-20T13:38:41", "EndTime": "2026-12-31T23:59:59",
    }
    j = BeisenAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None).normalize(raw)
    assert j.publish_at == "2026-09-20"
    assert j.apply_end == "2026-12-31"

    raw["PostDate"] = "0001-01-01T00:00:00"
    raw["EndTime"] = "0001-01-01T00:00:00"
    j = BeisenAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None).normalize(raw)
    assert j.publish_at is None, "0001-01-01 是未填哨兵，不能当日期"
    assert j.apply_end is None


def test_placeholder_jd_is_dropped():
    """有的租户把 Duty/Require 填成 `"1"`（2026-10-26 实测货拉拉 202/534 条）。

    落库等于把「JD 覆盖率 100%」变成假数字 —— 抓取质量报告会据此误判。
    判据只看长度（去空白后 <10 字符），不猜内容。
    """
    from jobradar.adapters.beisen import BeisenAdapter

    base = {"Id": "x-2", "JobAdName": "综合专员(J23379)", "CategoryId": "1", "LocNames": []}
    a = BeisenAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    for junk in ("1", "无", "-", "N/A", "  1 ", ""):
        j = a.normalize({**base, "Duty": junk, "Require": junk})
        assert j.description is None, f"{junk!r} 不是正文"
        assert j.requirements is None

    real = "负责门店日常运营，包括排班、库存与客户服务。"
    j = a.normalize({**base, "Duty": real, "Require": None})
    assert j.description == real


def test_change_date_fills_in_when_both_date_fields_are_sentinels():
    """`PostDate`/`EndTime` 都是哨兵时退到 `ChangeDate`。

    实测：京东方、海信、康弘三个租户的 `PostDate` 全空或全是哨兵，`ChangeDate` 是
    真实的「最后修改时间」（同一批导入的岗位该值逐秒相同）。有它总比没有强——
    日历条目至少要能落在「这一批什么时候挂出来的」附近。
    """
    raw = {"Id": "x1", "JobAdName": "临床监查员(J001)", "CategoryId": "2",
           "PostDate": "0001-01-01T00:00:00", "EndTime": "0001-01-01T00:00:00",
           "ChangeDate": "2026-04-01T15:15:46.6127253", "Duty": "d" * 20}
    job = BeisenAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    j = job.normalize(raw)
    assert j.publish_at == "2026-04-01"


def test_real_post_date_wins_over_change_date():
    """有真 `PostDate` 时不能被 `ChangeDate` 覆盖：前者才是「挂出来的时间」。"""
    raw = {"Id": "x2", "JobAdName": "临床监查员(J002)", "CategoryId": "2",
           "PostDate": "2026-09-20T00:00:00", "EndTime": "0001-01-01T00:00:00",
           "ChangeDate": "2026-10-25T09:00:00", "Duty": "d" * 20}
    a = BeisenAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    assert a.normalize(raw).publish_at == "2026-09-20"


def test_cities_from_province_city_district_strings():
    """`LocNames` 的真实形态是 `省·市` / `省·市·区`（间隔号 U+00B7），要取市级那段。

    整串塞进 cities 的话，用户搜「合肥」永远搜不到——而合肥恰恰是长鑫存储 2026 条岗位的主城市。
    """
    from jobradar.adapters.beisen import cities_of

    assert cities_of(["安徽省·合肥市", "北京市", "上海市"]) == ["合肥", "北京", "上海"]
    assert cities_of(["广东省·广州市·花都区"]) == ["广州"]
    assert cities_of(["上海市·静安区"]) == ["上海"]
    assert cities_of(["新疆维吾尔自治区·乌鲁木齐市"]) == ["乌鲁木齐"]
    assert cities_of(["香港特别行政区"]) == ["香港"]
    # 海外站点照原样保留，不做臆测翻译
    assert cities_of(["日本"]) == ["日本"]
    assert cities_of([]) == [] and cities_of(None) == []


def test_title_fallback_when_loc_names_missing():
    """`LocNames` 为空时退到标题抽取（药明合联 179/634 条，但门户页面上地点列是显示出来的）。

    只在字段为空时兜底——字段有值时它是权威，不能被标题覆盖。
    """
    a = BeisenAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    base = {"Id": "x9", "CategoryId": "1", "Duty": "d" * 20}

    j = a.normalize({**base, "JobAdName": "有机合成研究员-苏州(J25210)", "LocNames": []})
    assert j.cities == ["苏州"]

    # 字段给了就以字段为准
    j = a.normalize({**base, "JobAdName": "有机合成研究员-苏州(J25210)",
                     "LocNames": ["湖北省·武汉市"]})
    assert j.cities == ["武汉"]

    # 抽不出城市的标题不能硬猜
    for t in ("高级销售经理(J1)", "化学业务平台研发化学服务部(J2)", "上海大众汽车工程师(J3)"):
        assert a.normalize({**base, "JobAdName": t, "LocNames": []}).cities == [], t


def test_province_only_location_is_not_a_city():
    """`LocNames: ["湖北省"]` 是省级大区，不是办公城市（实测北森自己的门户）。

    标题写「（华中战区/武汉）」。把「湖北」当城市落库，搜「武汉」的人会漏掉这批岗，
    搜「湖北」的人又会看到其实在长沙的岗——两种都比留空糟。所以返回空、让标题兜底。
    """
    from jobradar.adapters.beisen import cities_of

    assert cities_of(["湖北省"]) == []
    assert cities_of(["福建"]) == []
    assert cities_of(["湖南"]) == []
    # 直辖市 / 特别行政区本身就是城市
    assert cities_of(["北京"]) == ["北京"]
    assert cities_of(["上海市"]) == ["上海"]
    assert cities_of(["香港特别行政区"]) == ["香港"]
    # 有市级信息时不受影响
    assert cities_of(["湖北省", "湖北省·武汉市"]) == ["武汉"]
    assert cities_of(["安徽省·合肥市"]) == ["合肥"]

    a = BeisenAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    j = a.normalize({"Id": "x11", "CategoryId": "1", "Duty": "d" * 20,
                     "JobAdName": "软件客户经理（华中战区/武汉）(J14892)", "LocNames": ["湖北省"]})
    assert j.cities == ["武汉"]


def test_white_label_host_replaces_zhiye_domain():
    """白标域名（`zhaopin.joyoung.com`）时，列表和详情都必须打到白标域上。

    2026-10-27 实测：北森允许公司把门户 CNAME 到自己域名，接口原样挂在白标域，
    但 tenant 猜不到（`joyoung.zhiye.com` 302 到 /404）。没有 host 参数时这些门户永远接不进来。
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("GetJobAdPageList"):
            return httpx.Response(200, json={"Code": 200, "Count": 0, "Data": []})
        return httpx.Response(200, json={})

    src = source()
    src.params = {**src.params, "host": "zhaopin.joyoung.com"}
    a = BeisenAdapter(src, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    list(a.fetch_all())
    assert seen and all("zhaopin.joyoung.com" in u for u in seen), seen
    assert not any("zhiye.com" in u for u in seen), seen
