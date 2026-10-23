from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.hotjob_legacy import HotjobLegacyAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "hotjob_legacy"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = HotjobLegacyAdapter(source(**params), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    """伊利 2027 校招数字化培训生：列表 JSON 自带 JD，城市只取城市级。"""
    j = next(j for j in run() if j.source_job_id == "533317")
    assert j.company == "伊利"
    assert j.title == "伊利2027届校招-数字化培训生（婴幼儿 北京）"
    assert j.recruit_type == "campus"
    assert j.cities == ["北京"]                       # workPlace「北京市-丰台区」
    assert j.degree_min == "硕士研究生及以上"
    assert j.grad_year == 2027
    assert j.department
    assert j.url.startswith("https://yili.hotjob.cn/wt/yili/web/index/webPositionN300!getOnePosition")


def test_list_carries_jd_so_every_record_has_text():
    """老版 wt 的列表响应里就有 workContent/serviceCondition，不需要详情请求。"""
    jobs = run()
    assert len(jobs) >= 10
    assert all(j.description and j.requirements for j in jobs)


def test_missing_title_is_skipped():
    """脏数据不能把整次抓取带崩：没有 postId/postName 的记录抛 SkipRecord。"""
    a = HotjobLegacyAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    with pytest.raises(SkipRecord):
        a.normalize({"item": {"postId": 1, "postName": ""}, "recruit_type": "campus"})
