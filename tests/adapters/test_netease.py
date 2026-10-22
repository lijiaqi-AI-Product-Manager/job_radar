from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.netease import NeteaseAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "netease"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = NeteaseAdapter(source(**params), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    j = next(j for j in run() if j.source_job_id == "4839")
    assert j.id == "netease:4839"
    assert j.company == "网易"
    assert j.title == "营销推广专员（网易智邮）"
    assert j.recruit_type == "campus"
    assert j.grad_year == 2027          # 来自项目名「网易互联网2027届校园招聘」
    assert j.cities == ["北京"]
    assert j.url == "https://campus.163.com/app/job/position?id=103"
    assert j.description.startswith("1、协助SEM")
    assert j.requirements.startswith("1、本科及以上学历")


def test_every_job_has_jd_text():
    jobs = run()
    assert len(jobs) == 3
    assert all(j.description and j.requirements for j in jobs)


def test_stops_at_max_pages():
    """fixtures 只录了 1 页；若没按 max_pages/分页终止，回放会因缺少请求而失败。"""
    jobs = run()          # 回放命中唯一一条响应即通过
    assert len(jobs) == 3


def test_unusable_record_is_skipped():
    a = NeteaseAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({}, {"id": 1}, {"positionName": "算法"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)


def test_api_error_is_raised():
    def handler(request):
        return httpx.Response(200, json={"code": 500, "msg": "boom", "data": None})

    a = NeteaseAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="code=500"):
        list(a.fetch_all())
