"""云就业 SaaS 高校就业网（yunjiuye）适配器测试。

用 httpx.MockTransport 造两个响应，覆盖三件事：
1. `/module/getjobs` 的 JSON 字段能落进 Job（岗位名/城市/学历/发布日/截止日/实习口径）；
2. 归属闸门：company_name 与 params.match 归一后不相等就 0 条；
3. 详情页 JD 抽取只留正文，不把导航/页脚吞进来。
"""

from __future__ import annotations

import json

import httpx

from jobradar.adapters.yunjiuye import (
    YunjiuyeAdapter,
    company_core,
    same_company,
)
from jobradar.models import SourceConfig

HOST = "demo.bysjy.com.cn"
JOBS = {
    "code": 1,
    "msg": "",
    "data": [
        {
            "publish_id": "900001",
            "company_id": "1",
            "company_name": "中交一公局集团有限公司",
            "job_name": "桥梁设计工程师",
            "city_name": "北京市",
            "publish_time": "2026-10-20",
            "end_time": "2026-11-30",
            "salary": "10K-15K/月",
            "degree_require": "硕士及以上",
            "about_major": "土木工程",
            "is_practice": "0",
            "category": "工程技术人员",
        },
        {
            "publish_id": "900002",
            "company_id": "1",
            "company_name": "中交一公局集团有限公司",
            "job_name": "工程测量实习生",
            "city_name": "天津市",
            "publish_time": "2026-10-21",
            "end_time": "",
            "salary": "3K-5K/月",
            "degree_require": "本科及以上",
            "about_major": "测绘",
            "is_practice": "1",
            "category": "",
        },
        {
            "publish_id": "900003",
            "company_id": "2",
            "company_name": "别家公司有限公司",
            "job_name": "会计",
            "city_name": "上海市",
            "publish_time": "2026-10-22",
            "end_time": "",
            "degree_require": "本科",
            "is_practice": "0",
        },
    ],
}
DETAIL = """
<html><body><nav>首页 宣讲会 双选会</nav>
<div class="job-title">桥梁设计工程师</div>
<div class="job-content"><h3>岗位职责</h3><p>负责桥梁结构设计与计算。</p>
<h3>任职要求</h3><p>硕士及以上，土木工程专业。</p></div>
<div class="unit">单位信息</div><div>中交一公局集团有限公司</div>
<footer>版权所有</footer></body></html>
"""


COMPLIANCE = {
    "checked_on": "2026-10-30",
    "robots": "allowed",
    "terms": "高校就业网公开职位列表，无需登录",
    "notes": "测试用",
}


def _source(**params) -> SourceConfig:
    return SourceConfig(
        id="yunjiuye-demo",
        company="中交一公局",
        adapter="yunjiuye",
        params={"host": HOST, "match": ["中交一公局集团有限公司"], **params},
        compliance=COMPLIANCE,
    )


def _adapter(match: list[str], *, fetch_detail: bool = True) -> YunjiuyeAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/module/getjobs":
            return httpx.Response(200, json=JOBS)
        if request.url.path == "/detail/job":
            return httpx.Response(200, text=DETAIL)
        return httpx.Response(404)

    source = _source(match=match, fetch_detail=fetch_detail)
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=f"https://{HOST}")
    return YunjiuyeAdapter(source, client)


def test_parse_jobs_into_model() -> None:
    jobs = list(_adapter(["中交一公局集团有限公司"]).fetch_all())
    assert [j.source_job_id for j in jobs] == ["900001", "900002"]
    first = jobs[0]
    assert first.company == "中交一公局"
    assert first.title == "桥梁设计工程师"
    assert first.cities == ["北京市"]
    assert first.degree_min == "硕士"
    assert first.publish_at == "2026-10-20"
    assert first.apply_end == "2026-11-30"
    assert first.recruit_type == "campus"
    assert first.url == f"https://{HOST}/detail/job?id=900001"
    assert jobs[1].recruit_type == "intern"


def test_jd_extracted_without_nav_or_footer() -> None:
    job = next(iter(_adapter(["中交一公局集团有限公司"]).fetch_all()))
    assert job.description
    assert "负责桥梁结构设计与计算" in job.description
    assert "版权所有" not in job.description
    assert "单位信息" not in job.description


def test_ownership_gate() -> None:
    assert list(_adapter(["中交二公局集团有限公司"]).fetch_all()) == []


def test_company_core_and_same_company() -> None:
    assert company_core("中交一公局集团有限公司") == "中交一公局"
    assert same_company("中交一公局集团有限公司", "中交一公局")
    assert not same_company("中交二公局集团有限公司", "中交一公局")


def test_fetch_detail_can_be_disabled() -> None:
    jobs = list(_adapter(["中交一公局集团有限公司"], fetch_detail=False).fetch_all())
    assert jobs and all(j.description is None for j in jobs)


def test_list_shape_is_json() -> None:
    """接口返回必须是带 code=1 的 JSON，否则视为空（防止把 HTML 错误页当数据）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>error</html>")

    source = _source()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert list(YunjiuyeAdapter(source, client).fetch_all()) == []


def test_requires_host_param() -> None:
    source = SourceConfig(
        id="yunjiuye-demo", company="X", adapter="yunjiuye", params={}, compliance=COMPLIANCE
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    try:
        YunjiuyeAdapter(source, client)
    except ValueError as exc:
        assert "host" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("缺 host 应当直接报错")


def test_json_module_roundtrip() -> None:
    """确保测试里的假数据本身是合法 JSON（避免误把 Python dict 当接口响应）。"""
    assert json.loads(json.dumps(JOBS))["data"][0]["publish_id"] == "900001"
