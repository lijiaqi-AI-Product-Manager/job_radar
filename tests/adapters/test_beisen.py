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
    assert j.cities == []  # 列表接口不提供城市（已知缺口），不从标题猜


def test_social_record_mapping():
    j = by_title(run(), "品牌传播高级总监(J13868)")
    assert j.recruit_type == "social"
    assert j.grad_year is None and j.batch is None
    assert "/social/detail?jobAdId=" in j.url


def test_type_mix_matches_category_ids():
    jobs = run()
    assert sum(j.recruit_type == "campus" for j in jobs) == 33
    assert sum(j.recruit_type == "social" for j in jobs) == 7


def test_recruit_types_filter():
    jobs = run(source(recruit_types=["campus"]))
    assert {j.recruit_type for j in jobs} == {"campus"}


def test_unknown_category_and_missing_fields_are_skipped():
    a = BeisenAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({"Id": "x", "JobAdName": "t", "CategoryId": "9"},
                {"Id": "", "JobAdName": "t", "CategoryId": "2"},
                {"Id": "x", "JobAdName": "", "CategoryId": "2"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)


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
