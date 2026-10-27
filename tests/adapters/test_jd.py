from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.jd import JdAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "jd"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run():
    adapter = JdAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(adapter.fetch_all())


def test_field_mapping_of_real_record():
    jobs = {j.source_job_id: j for j in run()}
    j = jobs["9420"]
    assert j.company == "京东"
    assert j.title == "弱先验环境下物流无人机全自主飞行研究"
    assert j.recruit_type == "campus"          # TGT 正式计划
    assert j.cities == ["深圳"]                 # 城市来自 requirementVoList[].workCity
    assert j.publish_at == "2026-10-23"        # publishTime 毫秒时间戳 -> 日期
    assert j.subcategory == "TGT"
    assert j.url == "https://campus.jd.com/#/job/detail/9420"
    assert j.description and j.requirements


def test_tgt_intern_plan_is_not_counted_as_campus():
    """talent 里的 55 是「TGT-顶尖青年技术实习生」，不能跟着 talent 一起算校招。"""
    jobs = {j.source_job_id: j for j in run()}
    assert jobs["9416"].recruit_type == "intern"
    assert jobs["9420"].recruit_type == "campus"


def test_all_three_project_types_are_covered():
    kinds = {j.recruit_type for j in run()}
    assert kinds == {"campus", "intern"}


def test_multi_city_union_is_complete():
    """一个岗位可挂多个需求城市，全部并进 cities（京东这块给得很全）。"""
    big = max(run(), key=lambda j: len(j.cities))
    assert len(big.cities) > 20
    assert "北京" in big.cities and "上海" in big.cities


def test_missing_id_or_title_is_skipped():
    a = JdAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({"positionName": "x", "_type": "present", "_plan": "JDS"},
                {"publishId": 1, "positionName": "  ", "_type": "present", "_plan": "JDS"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)


def test_plan_ids_come_from_project_list_not_hardcoded():
    """planId 必须来自项目字典接口，不能写死在代码里——京东随时会加/停项目。"""
    seen = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"success": True, "body": {"projectList": [
                {"code": "present", "release": True, "groupList": [
                    {"planMapList": [{"id": 999, "planName": "自定义计划"}]}]},
                {"code": "present", "release": False, "groupList": [   # 未发布，应跳过
                    {"planMapList": [{"id": 111, "planName": "下线计划"}]}]},
            ]}})
        body = request.content.decode()
        seen.append(body)
        return httpx.Response(200, json={"success": True, "body": {"totalNumber": 1, "items": [
            {"publishId": 1, "positionName": "岗位", "jobDirection": "技术"}]}})

    s = source()
    s.params = {}
    a = JdAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    jobs = list(a.fetch_all())
    assert len(jobs) == 1
    assert any("999" in b for b in seen)
    assert not any("111" in b for b in seen)


def test_page_index_starts_at_zero():
    """pageIndex 从 0 开始（不是 1）；写成 1 会直接漏掉第一页。"""
    idx = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"success": True, "body": {"projectList": [
                {"code": "present", "release": True, "groupList": [
                    {"planMapList": [{"id": 56, "planName": "JDS"}]}]}]}})
        import json as _json
        idx.append(_json.loads(request.content)["pageIndex"])
        return httpx.Response(200, json={"success": True, "body": {"totalNumber": 3, "items": [
            {"publishId": len(idx), "positionName": "岗位"}]}})

    s = source()
    s.params = {"page_size": 1}
    a = JdAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    list(a.fetch_all())
    assert idx == [0, 1, 2]


def test_lowercase_failure_field_raises():
    def handler(request):
        return httpx.Response(200, json={"success": False, "message": "系统繁忙"})

    a = JdAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="系统繁忙"):
        list(a.fetch_all())
