from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.recording import ReplayTransport
from jobradar.adapters.workday import WorkdayAdapter, cities_of, country_locations, recruit_type_of
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "workday"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = WorkdayAdapter(source(**params), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    j = next(j for j in run() if "Power-and-Performance" in j.source_job_id)
    assert j.company == "英伟达"
    assert j.title == "Senior Power and Performance Engineer"
    assert j.recruit_type == "social"
    assert j.cities == ["上海"]
    assert j.url.startswith("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/China-Shanghai/")
    assert j.description.startswith("NVIDIA's Silicon Co-design Group")
    assert j.requirements is None  # JD 是整段 HTML，职责与要求在同一段里


def test_every_job_has_jd_text():
    jobs = run()
    assert len(jobs) == 3
    assert all(j.description and len(j.description) > 200 for j in jobs)


def test_intern_title_maps_to_intern():
    """标题里明写 Intern 的岗位按实习入库（NVIDIA 站内是 Univ Employment）。"""
    jobs = {j.title: j for j in run()}
    intern = next(j for t, j in jobs.items() if "Intern" in t)
    assert intern.recruit_type == "intern"


@pytest.mark.parametrize("title,default,expected", [
    ("GPU Computing Software Engineering Intern, Autonomous Driving - 2027", "social", "intern"),
    ("Internal Tools Engineer", "social", "social"),          # \b 边界，不误判 Internal
    ("New College Graduate - Software Engineer", "social", "campus"),
    ("Senior Power Engineer", "social", "social"),
])
def test_recruit_type_of(title, default, expected):
    assert recruit_type_of(title, default) == expected


def test_country_locations_picks_only_that_country():
    facets = [{"facetParameter": "locationMainGroup", "descriptor": "Location", "values": [
        {"facetParameter": "locations", "descriptor": "Sites", "values": [
            {"descriptor": "China, Shanghai", "id": "cn-sh"},
            {"descriptor": "China, Beijing", "id": "cn-bj"},
            {"descriptor": "United States, Austin", "id": "us-atx"},
        ]},
    ]}]
    assert country_locations(facets, "China") == ["cn-sh", "cn-bj"]
    assert country_locations(facets, "Japan") == []


@pytest.mark.parametrize("location,cities", [
    ("China, Shanghai", ["上海"]),
    ("China, Beijing", ["北京"]),
    ("United States, Austin", []),
    (None, []),
])
def test_cities_of(location, cities):
    assert cities_of(location) == cities


def test_missing_country_facet_fails_instead_of_ingesting_global_jobs():
    """找不到中国分面时必须失败（不能把全球 2000 个岗位灌进数据集）。"""
    def handler(request):
        return httpx.Response(200, json={"total": 2000, "jobPostings": [
            {"title": "x", "externalPath": "/job/x", "locationsText": "US"}], "facets": []})

    a = WorkdayAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="China"):
        list(a.fetch_all())


def test_pagination_ignores_total_after_first_page():
    """Workday 从第二页起返回 total=0（实测），不能因此提前停止翻页。"""
    a = WorkdayAdapter(source(page_size=20, max_pages=99), httpx.Client(), sleep=lambda s: None)
    pages = {0: (20, 244), 20: (20, 0), 40: (3, 0)}
    seen = []

    def fake(method, url, *, params=None, json=None, headers=None):
        if url.endswith("/jobs"):
            if json.get("limit") == 1:  # facets 探测请求
                return {"total": 244, "jobPostings": [], "facets": [{
                    "facetParameter": "locations", "values": [
                        {"descriptor": "China, Shanghai", "id": "cn-sh"}]}]}
            off = json["offset"]
            seen.append(off)
            n, total = pages[off]
            return {"total": total, "jobPostings": [
                {"title": f"J{off + i}", "externalPath": f"/job/{off + i}"} for i in range(n)]}
        return {"jobPostingInfo": {"title": "x", "jobDescription": "<p>jd</p>"}}

    a.request_json = fake
    jobs = list(a.fetch_all())
    assert len(jobs) == 43 and seen == [0, 20, 40]


def test_unusable_record_is_skipped():
    a = WorkdayAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({}, {"title": "x"}, {"externalPath": "/job/x"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)

def test_country_locations_accepts_three_country_formats():
    """实测遇到的三种写法：China, Shanghai（多数）/ China - Shanghai - Shanghai（辉瑞）/ China（阿斯利康）。"""
    from jobradar.adapters.workday import country_locations
    facets = [{"facetParameter": "locations", "values": [
        {"descriptor": "China, Shanghai", "id": "a"},
        {"descriptor": "China - Beijing - Beijing", "id": "b"},
        {"descriptor": "China", "id": "c"},
        {"descriptor": "Chinatown, CA", "id": "bad"},
        {"descriptor": "USA, Austin", "id": "d"},
    ]}]
    assert country_locations(facets, "China") == ["a", "b", "c"]


def test_country_locations_exact_mode_uses_given_facet():
    """辉瑞用 Location_Country 分面，descriptor 就是国家名，必须精确匹配。"""
    from jobradar.adapters.workday import country_locations
    facets = [{"facetParameter": "Location_Country", "values": [
        {"descriptor": "China", "id": "cn"},
        {"descriptor": "China, Hong Kong", "id": "hmm"},
    ]}]
    assert country_locations(facets, "China", facet="Location_Country", prefix_match=False) == ["cn"]

def test_cities_of_many_reads_additional_locations():
    """多地点岗位：Workday 详情里 location + additionalLocations 都要解析。

    真实样本（辉瑞）：location="China - Jiangsu - LianYungang"，
    additionalLocations=["China - Jiangsu - Yancheng", "China - Jiangsu - Huai'An"]。
    """
    from jobradar.adapters.workday import cities_of_many
    got = cities_of_many("China - Shanghai - Shanghai",
                         ["China - Beijing - Beijing"], "2 Locations")
    assert got == ["上海", "北京"]


def test_cities_of_many_ignores_placeholder_text():
    from jobradar.adapters.workday import cities_of_many
    assert cities_of_many("2 Locations") == []
    assert cities_of_many(None, []) == []


def test_china_lake_is_not_china():
    """`USA - China Lake, CA` 是加州的中国湖（海军航空站），不是中国岗位。

    原来的判据是 `country.lower() in locations_text.lower()`，只要串里有 "China"
    就算命中——2026-10-26 实测波音（boeing.wd1）的 3 条 "China" 命中里就有它。
    现在改成「按 `,` `-` `/` 切段后某段整体等于国家名/CN/CHN」。
    """
    from jobradar.adapters.workday import _in_country

    assert _in_country("USA - China Lake, CA", "China") is False
    assert _in_country("APAC - China Lake", "China") is False
    # 真中国岗位的各种写法都要放过
    for good in ("Dalian-Liaoning-China", "China - Shanghai", "CHN - Beijing, China",
                 "Beijing, China", "Shanghai, China", "Pudong, Shanghai"):
        assert _in_country(good, "China") is True, good
    # 没有地名的「N Locations」一律不放行
    assert _in_country("3 Locations", "China") is False


def test_hyphenated_location_parses_city():
    """Workday 的 `Dalian-Liaoning-China` 是「城市-省-国家」用**裸连字符**连起来的。

    原来只按 `" - "`（带空格）和 `,` 切，整串丢给 `city_from_english` 一个都匹配不上：
    江森自控 63 条岗位城市 100% 丢失（2026-10-26 实测）。
    """
    from jobradar.adapters.workday import cities_of

    assert cities_of("Dalian-Liaoning-China") == ["大连"]
    assert cities_of("Shanghai-Shanghai-China") == ["上海"]
    assert cities_of("Macau-Macau-China-Macau (SAR)") == ["澳门"]
    assert cities_of("Beijing, China") == ["北京"]
    assert cities_of("USA - China Lake, CA") == []      # 加州中国湖不是中国城市
    assert cities_of("Bangalore-Karnataka-India") == []


def test_remote_location_becomes_remote_tag():
    """`China---Remote` 是官方写明的远程岗（雅培 42 条）。

    留空会让「搜远程」搜不到它——地点信息本身是对的，只是它不是城市。
    """
    from jobradar.adapters.workday import cities_of

    assert cities_of("China---Remote") == ["远程"]
    assert cities_of("Remote - China") == ["远程"]
    assert cities_of("Dalian-Liaoning-China") == ["大连"]   # 有城市时不能被「远程」占位
