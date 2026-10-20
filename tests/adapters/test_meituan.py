from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.meituan import MeituanAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "meituan"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run():
    a = MeituanAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    j = next(j for j in run() if j.source_job_id == "4697320043")
    assert j.id == "meituan:4697320043"
    assert j.company == "美团"
    assert j.title == "AI全栈工程师"
    assert j.recruit_type == "campus"
    assert j.cities == ["北京", "上海", "成都", "深圳"]
    assert j.url == "https://zhaopin.meituan.com/web/position/detail?jobUnionId=4697320043&highlightType=campus"
    assert j.description.startswith("岗位职责\n1. 参与 AI 应用的全栈开发")
    assert j.requirements.startswith("岗位要求\n1. 本科及以上学历")
    assert j.department is None  # 原始 department 为空列表


def test_whole_page_is_parsed():
    jobs = run()
    assert len(jobs) == 5 and len({j.id for j in jobs}) == 5


def test_recruit_type_mapping_and_skips():
    a = MeituanAdapter(source(), httpx.Client(), sleep=lambda s: None)
    base = {"jobUnionId": "1", "name": "运营实习生", "cityList": [{"name": "北京市"}]}
    assert a.normalize({**base, "jobType": "2"}).recruit_type == "intern"
    social = a.normalize({**base, "jobType": "3", "department": [{"name": "到家事业群"}]})
    assert social.recruit_type == "social" and social.department == "到家事业群"
    assert "highlightType=social" in social.url
    for raw in ({**base, "jobType": "9"}, {**base, "jobType": "1", "name": ""}, {"name": "x", "jobType": "1"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)


def test_stops_at_total_page():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"data": {"list": [{"jobUnionId": str(len(calls)), "name": "A", "jobType": "1"}],
                                                  "page": {"pageNo": len(calls), "totalPage": 2}}})

    s = source()
    s.params = {k: v for k, v in s.params.items() if k != "max_pages"}
    a = MeituanAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert len(list(a.fetch_all())) == 2 and len(calls) == 2


def test_unexpected_response_raises():
    a = MeituanAdapter(source(), httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"code": 500, "msg": "error"}))), sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        list(a.fetch_all())
