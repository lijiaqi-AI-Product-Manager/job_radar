"""jsonportal（自建 SPA 门户 → 公开 JSON 接口）适配器的测试。

fixtures：tests/fixtures/jsonportal/，录自中国电子校招门户
（`campus.cec.com.cn/student-api/api/position/search`，2026-10-27）。
"""
from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import USER_AGENT, SkipRecord, make_client
from jobradar.adapters.jsonportal import JsonPortalAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "jsonportal"


def source(**kw):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data.update(kw)
    return SourceConfig(**data)


def run(src=None):
    a = JsonPortalAdapter(src or source(), httpx.Client(transport=ReplayTransport(FX)),
                          sleep=lambda s: None)
    return list(a.fetch_all())


def test_two_pages_are_fetched():
    """分页参数名（`page`/`size`）传错时服务端不报错、永远回第 1 页——
    实测就是这样把 788 岗抓成 20 条。这条守的是「真的翻页了」。"""
    jobs = run()
    assert len(jobs) == 20
    assert len({j.source_job_id for j in jobs}) == 20


def test_field_mapping():
    j = run()[0]
    assert j.source_id == "jsonportal-cec"
    assert j.title == "软件开发工程师 （深圳）"
    assert j.cities == ["深圳"]
    assert j.recruit_type == "campus"
    assert j.apply_end and j.apply_end.startswith("2026-")
    assert j.url == "https://campus.cec.com.cn/position?positionType=0"


def test_jd_split_into_description_and_requirements():
    """接口把 JD 拆成 jobDescription / jobRequirements 两段，必须各自落到对应字段，
    拼成一段会让「要求」和「职责」混在一起，下游按字段取用就取错了。"""
    jobs = run()
    with_both = [j for j in jobs if j.description and j.requirements]
    assert with_both, "至少要有一条同时有职责和要求"
    assert all(j.description != j.requirements for j in with_both)


def test_city_suffix_is_stripped():
    jobs = run()
    assert all(not c.endswith("市") for j in jobs for c in j.cities)


def test_missing_title_is_skipped():
    a = JsonPortalAdapter(source(), httpx.Client(transport=ReplayTransport(FX)),
                          sleep=lambda s: None)
    for raw in ({"name": ""}, {"name": "   "}, {}):
        try:
            a.normalize(raw)
        except SkipRecord:
            continue
        raise AssertionError(f"应当 SkipRecord: {raw}")


def test_type_param_limits_recruit_types():
    """只配 campus 时不该把社招那一路也翻出来（社招岗挂 2027 届是错的）。"""
    jobs = run(source(recruit_types=["campus"]))
    assert {j.recruit_type for j in jobs} == {"campus"}


def test_public_listing_link_uses_the_requested_recruitment_channel():
    src = source()
    src.params["detail_url"] = "https://campus.cec.com.cn/position?positionType={type_value}"
    src.params["type_param"] = {"positionType": {"campus": 0, "social": 1}}
    adapter = JsonPortalAdapter(src, httpx.Client(), sleep=lambda seconds: None)
    for rtype, value in (("campus", 0), ("social", 1)):
        job = adapter.normalize({"id": "sample", "name": "软件工程师", "__recruit_type": rtype})
        assert job.url == f"https://campus.cec.com.cn/position?positionType={value}"


def test_listing_route_does_not_guess_an_unconfigured_channel():
    src = source()
    src.params["detail_url"] = "https://campus.cec.com.cn/position?positionType={type_value}"
    adapter = JsonPortalAdapter(src, httpx.Client(), sleep=lambda seconds: None)
    with pytest.raises(ValueError, match="配置映射"):
        adapter.normalize({"id": "sample", "name": "软件工程师", "__recruit_type": "intern"})


def test_source_config_cannot_override_the_fixed_project_user_agent():
    src = source()
    src.params = {**src.params, "user_agent": "different-agent"}
    with make_client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        JsonPortalAdapter(src, client)
        assert client.headers["User-Agent"] == USER_AGENT
