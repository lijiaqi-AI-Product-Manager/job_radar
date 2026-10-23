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
