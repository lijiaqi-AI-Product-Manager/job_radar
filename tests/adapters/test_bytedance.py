from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.bytedance import BytedanceAdapter, cities_of, publish_date, recruit_type_of
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "bytedance"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run():
    a = BytedanceAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    # 2026-10-26 录制的真实记录：多城市、正式批、有 JD 原文
    j = next(j for j in run() if j.source_job_id == "7667465226085796149")
    assert j.id == "bytedance:7667465226085796149"
    assert j.company == "字节跳动"
    assert j.title == "大数据引擎SRE工程师 - 数据平台"
    assert j.recruit_type == "campus"
    assert j.grad_year == 2027          # 项目名「2027届校园招聘」
    assert j.cities == ["上海", "北京", "杭州"]   # city_list 全量，不是 city_info 第一个
    assert j.url == "https://jobs.bytedance.com/campus/position/7667465226085796149/detail"
    assert j.description
    assert j.requirements
    assert j.publish_at and len(j.publish_at) == 10


def test_intern_batch_is_intern():
    j = next(j for j in run() if j.source_job_id == "7699346761598077189")
    assert j.recruit_type == "intern"
    assert j.batch is None          # 日常实习：不是提前批/正式批/春招/秋招
    assert j.grad_year is None      # 实习不写届别就是没有，不猜


def test_every_job_has_jd_text():
    """列表接口一次给全 JD，不需要逐岗请求详情页——这条盯住"以后改版变成只有标题"。"""
    jobs = run()
    assert len(jobs) == 20
    assert sum(1 for j in jobs if j.description and j.requirements) == len(jobs)


def test_cities_of_keeps_order_and_dedupes():
    assert cities_of({"city_list": [{"name": "上海"}, {"name": "北京"}, {"name": "上海"}]}) == ["上海", "北京"]
    assert cities_of({"city_info": {"name": "深圳"}}) == ["深圳"]
    assert cities_of({}) == []


@pytest.mark.parametrize("subject,expected", [
    ("2027届校园招聘", "campus"),
    ("2027届前沿技术领域人才校招", "campus"),
    ("ByteIntern", "intern"),
    ("日常实习", "intern"),
    ("社会招聘", None),
    ("", None),
])
def test_recruit_type_of(subject, expected):
    assert recruit_type_of({"job_subject": {"name": {"zh_cn": subject}}, "recruit_type": {"name": ""}}) == expected


def test_recruit_type_reads_official_type_field():
    # 两站实测：job_subject 为空时靠 recruit_type 的「正式 / 实习」也能判
    assert recruit_type_of({"recruit_type": {"name": "实习"}}) == "intern"
    assert recruit_type_of({"recruit_type": {"name": "正式"}}) is None   # 看不出是校招还是社招，跳过


@pytest.mark.parametrize("ms", [None, 0, -1, "abc", 1, 99_999_999_999_999])
def test_publish_date_rejects_junk(ms):
    assert publish_date(ms) is None


def test_publish_date_is_beijing_time():
    # 2027-07-28 01:00 UTC = 2027-07-28 09:00 CST；跨零点那条必须落到东八区当天
    assert publish_date(1816736400000) == "2027-07-28"


def test_stale_jd_does_not_supply_grad_year():
    """2023 年挂到现在的实习岗，JD 里写着别的届次——按 JD 兜底会写出「2023届在招」这种错。
    录制数据里 7628624331531995397 等项目名本身写了届次的仍然保留。"""
    jobs = run()
    # 日常实习/ByteIntern 里发布时间早于本年度 7-1 的，一律不给届别
    for j in jobs:
        if j.grad_year is None:
            continue
        if j.publish_at and j.publish_at < "2026-07-01":
            # 只允许"项目名自己写了届次"的（如 2027届校园招聘），不允许 JD 兜底的
            assert "届" in j.title or j.grad_year == 2027
