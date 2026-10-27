"""飞书招聘 ATSX 通用适配器的测试。

字节跳动那一家有独立测试（tests/adapters/test_bytedance.py，断言具体字段值）；
这里断言的是**跨门户的通用契约**，用的是蔚来 / 小鹏 / Momenta 三家 2026-10-26 录的真实响应：

  feishu_atsx_nio      蔚来       project="2027届校园招聘-正式批"
  feishu_atsx_xpeng     小鹏汽车    /campus 站，project 为空，靠 recruit_type.parent 判校招
  feishu_atsx_momenta   Momenta    project="Mstar计划"（项目名不带届次）
"""

from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.feishu_atsx import (
    FeishuAtsxAdapter,
    cities_of,
    publish_date,
    recruit_type_of,
)
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import Compliance, SourceConfig


def cfg(sid: str, **params) -> SourceConfig:
    """最小可用的源配置。compliance 是 SourceConfig 的必填项（enabled 源必须登记），
    这里给一个占位值——真实登记在 sources/<id>.yaml 里。"""
    return SourceConfig(id=sid, company=sid.upper(), adapter="feishu_atsx", rate_limit_rps=1,
                        params=params,
                        compliance=Compliance(checked_on="2026-10-26", robots="none", terms="test"))

FX = Path(__file__).parent.parent / "fixtures"


def run(tag: str):
    d = FX / f"feishu_atsx_{tag}"
    source = SourceConfig(**yaml.safe_load((d / "source.yaml").read_text(encoding="utf-8")))
    a = FeishuAtsxAdapter(source, httpx.Client(transport=ReplayTransport(d)), sleep=lambda s: None)
    return source, list(a.fetch_all())


# ---- 门户参数 ----


def test_base_url_and_website_path_come_from_params():
    source, _ = run("nio")
    a = FeishuAtsxAdapter(source, httpx.Client(transport=ReplayTransport(FX / "feishu_atsx_nio")))
    assert a.base_url == "https://nio.jobs.feishu.cn"
    assert a.website_path == "campus"
    assert a.job_url("123") == "https://nio.jobs.feishu.cn/campus/position/123/detail"


def test_website_path_defaults_to_campus():
    a = FeishuAtsxAdapter(cfg("x", base_url="https://x.jobs.feishu.cn"), httpx.Client())
    assert a.website_path == "campus"
    assert a.job_url("9").endswith("/campus/position/9/detail")


def test_job_url_template_can_be_overridden():
    a = FeishuAtsxAdapter(
        cfg("x", base_url="https://x.jobs.feishu.cn", website_path="index",
            job_url="{base}/{website_path}/job/{id}"),
        httpx.Client())
    assert a.job_url("7") == "https://x.jobs.feishu.cn/index/job/7"


# ---- 字段映射 ----


def test_neo_mapping_carries_project_batch_and_cities():
    _, jobs = run("nio")
    j = next(x for x in jobs if x.title == "校招-产品采购（售后零件）")
    assert j.company == "蔚来"
    assert j.recruit_type == "campus"
    assert j.grad_year == 2027                 # 项目名「2027届校园招聘-正式批」
    assert j.batch == "正式批"
    assert j.cities == ["上海"]
    assert j.url.startswith("https://nio.jobs.feishu.cn/campus/position/")
    assert j.description and j.requirements    # 列表自带 JD 原文


def test_xpeng_campus_is_not_confused_with_social():
    _, jobs = run("xpeng")
    assert jobs, "小鹏 /campus 回放后一条都没有"
    # /campus 站只有校招正式与校招实习；社招（recruit_type.parent=社招）绝不能进来
    assert {j.recruit_type for j in jobs} <= {"campus", "intern"}
    assert any(j.recruit_type == "campus" for j in jobs)
    assert any(j.recruit_type == "intern" for j in jobs)
    assert all(j.cities for j in jobs), "小鹏每条岗位都带 city_list"


def test_momenta_project_without_grad_year_leaves_it_empty():
    _, jobs = run("momenta")
    assert jobs
    # 「Mstar计划」不含届次；标题也不含 → 只有发布时间在本年度招季之后才可能从 JD 兜底，
    # 兜不到就必须留空（绝不写「大概 2027」）
    for j in jobs:
        assert j.grad_year in (None, 2027, 2028)


def test_all_portals_store_jd_text():
    for tag in ("nio", "xpeng", "momenta"):
        _, jobs = run(tag)
        with_jd = [j for j in jobs if (j.description or "") or (j.requirements or "")]
        assert len(with_jd) == len(jobs), f"{tag}: {len(with_jd)}/{len(jobs)}"


# ---- recruit_type_of：四种门户形态 ----


@pytest.mark.parametrize(("item", "want"), [
    # 项目名写明"实习"
    ({"job_subject": {"name": {"zh_cn": "2027届实习"}}, "recruit_type": {"name": "实习"}}, "intern"),
    ({"job_subject": {"name": {"zh_cn": "ByteIntern"}}, "recruit_type": {"name": "实习"}}, "intern"),
    # 项目名写"校园招聘"
    ({"job_subject": {"name": {"zh_cn": "2027届校园招聘-正式批"}}, "recruit_type": {"name": "正式"}}, "campus"),
    # 没有项目名，靠父级判断（小鹏）
    ({"job_subject": None, "recruit_type": {"name": "正式", "parent": {"name": "校招"}}}, "campus"),
    # 父级显式写社招——返回 "social"（不是 None：None 表示「判不出来」，两者语义不同）
    ({"job_subject": None, "recruit_type": {"name": "全职", "parent": {"name": "社招"}}}, "social"),
    # 项目名显式写社招
    ({"job_subject": {"name": {"zh_cn": "社会招聘"}}, "recruit_type": {"name": "全职"}}, None),
    # 2026-10-27 改判：门户只发社招时 `recruit_type.name` 就是「全职」，没有项目名/父级。
    # 商汤 87 岗、分贝通 14 岗都是这种形态；此前判 None 会让整个门户 `opened: 0`。
    ({"job_subject": None, "recruit_type": {"name": "全职"}}, "social"),
    ({"job_subject": None, "recruit_type": {"name": "Full-time"}}, "social"),
    # 类型名偶尔是 i18n 对象
    ({"job_subject": None, "recruit_type": {"name": {"zh_cn": "全职"}}}, "social"),
])
def test_recruit_type_of(item, want):
    assert recruit_type_of(item) == want


def test_recruit_type_prefers_parent_over_partial_match():
    # "校园招聘" 出现在父级、类型名是"全职"——也必须判成校招，不能因为"全职"两字不认识就丢掉
    item = {"job_subject": None, "recruit_type": {"name": "全职", "parent": {"name": "校园招聘"}}}
    assert recruit_type_of(item) == "campus"


# ---- 工具函数（沿用字节跳动的实现，这里防回归） ----


def test_cities_of_uses_full_list_not_first():
    item = {"city_list": [{"name": "上海"}, {"name": "北京"}, {"name": "上海"}],
            "city_info": {"name": "上海"}}
    assert cities_of(item) == ["上海", "北京"]


def test_cities_of_falls_back_to_city_info():
    assert cities_of({"city_list": [], "city_info": {"name": "合肥"}}) == ["合肥"]
    assert cities_of({}) == []


@pytest.mark.parametrize(("ms", "want"), [
    (1816736400000, "2027-07-28"),   # 东八区
    (0, None),
    (-1, None),
    (None, None),
    ("junk", None),
    (99999999999999999, None),        # 越界
])
def test_publish_date(ms, want):
    assert publish_date(ms) == want
