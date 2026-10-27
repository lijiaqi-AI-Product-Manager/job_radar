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
    assert j.id == "tencent:2069057652431962112"
    assert j.company == "腾讯"
    assert j.title == "腾讯云-产品管理高级经理(深圳/北京)"
    assert j.recruit_type == "social"
    assert j.cities == ["深圳"]
    assert j.department == "CSIG"
    assert j.url == "https://careers.tencent.com/jobdesc.html?postId=2069057652431962112"
    assert j.description.startswith("1.为部门整体经营过程与结果负责")
    assert j.requirements.startswith("1.本科及以上学历，五年以上的云计算相关产品")  # 来自详情接口
    # 列表接口的 `LastUpdateTime` 是中文日期串「2026年10月21日」，`date_only()` 已能解析
    assert j.publish_at == "2026-10-21"


def test_whole_page_is_parsed_with_details():
    jobs = run()
    assert len(jobs) == 5
    assert all(j.url.startswith("https://") and j.requirements for j in jobs)


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
        if "ByPostId" in str(request.url):
            return httpx.Response(200, json={"Code": 404, "Data": None})  # 详情失败：要求留空，不影响列表
        return httpx.Response(200, json={"Code": 200, "Data": {"Count": 2, "Posts": [
            {"PostId": "1", "RecruitPostName": "a"}, {"PostId": "2", "RecruitPostName": "b"}]}})

    s = source()
    s.params = {}
    a = TencentAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    jobs = list(a.fetch_all())
    assert len(jobs) == 2 and all(j.requirements is None for j in jobs)
    assert len([c for c in calls if "Query" in c]) == 1


def test_api_error_code_raises():
    def handler(request):
        return httpx.Response(200, json={"Code": 500, "Data": None})

    a = TencentAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        list(a.fetch_all())
