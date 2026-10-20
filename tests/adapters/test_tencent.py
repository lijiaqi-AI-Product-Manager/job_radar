from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.recording import ReplayTransport
from jobradar.adapters.tencent import TencentAdapter
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "tencent"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run():
    adapter = TencentAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(adapter.fetch_all())


def test_field_mapping_of_real_record():
    j = run()[0]
    assert j.id == "tencent:2079604867550330880"
    assert j.company == "腾讯"
    assert j.title == "3A动作冒险游戏-战斗主策划"
    assert j.recruit_type == "social"
    assert j.cities == ["上海"]
    assert j.department == "IEG"
    assert j.url == "https://careers.tencent.com/jobdesc.html?postId=2079604867550330880"
    assert j.description.startswith("1.负责3A动作冒险游戏的战斗系统")
    assert j.requirements is None  # 列表接口不含岗位要求


def test_whole_page_is_parsed():
    jobs = run()
    assert len(jobs) == 50
    assert all(j.url.startswith("https://") for j in jobs)


def test_invalid_or_incomplete_records_are_skipped():
    a = TencentAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({"PostId": "1", "RecruitPostName": "x", "IsValid": False},
                {"PostId": "", "RecruitPostName": "x"},
                {"PostId": "1"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)


def test_pagination_stops_at_count_without_max_pages():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"Code": 200, "Data": {"Count": 2, "Posts": [
            {"PostId": "1", "RecruitPostName": "a"}, {"PostId": "2", "RecruitPostName": "b"}]}})

    s = source()
    s.params = {}
    a = TencentAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert len(list(a.fetch_all())) == 2 and len(calls) == 1


def test_api_error_code_raises():
    def handler(request):
        return httpx.Response(200, json={"Code": 500, "Data": None})

    a = TencentAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        list(a.fetch_all())
