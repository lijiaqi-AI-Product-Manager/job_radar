"""Tupu360 适配器契约测试。fixtures 由 scripts/record_fixtures.py tupu360-siemens 录制
（2026-10-26，max_pages=2, page_size=15, keep_details=4）。回放时 (method, url, body) 必须精确匹配，
所以这里同时锁住了「分页是 POST nextPageList + offset/max」这个最容易退化的点。

**不要为了压体积把 page_size 改成 5**：站点第 1 页 GET 固定给 15 条，而 POST 的 max=5 会让
第 2 页从 offset=5 开始、与第 1 页完全重叠 —— 回放时第 2 页 5 条全是「已见过的 pid」，
适配器会判定翻页失效并停在第 1 页，测试看起来还在跑但其实只覆盖了一半逻辑（2026-10-26 踩过）。
体积靠 --keep-details 与 --truncate 压，不靠改 page_size。
"""

from pathlib import Path

import httpx
import yaml

from jobradar.adapters.recording import ReplayTransport
from jobradar.adapters.tupu360 import Tupu360Adapter, _field, _job_id
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "tupu360"


def source(**params):
    """**不要**照抄 fixtures/source.yaml 的 params.max_pages —— 它记录的是「录制时翻了几页」，
    不是「回放时该翻几页」。2026-10-26 踩过：测试传 max_pages=1 被 yaml 里的 2 覆盖，
    断言 10 条却拿到 24 条，看了半天代码才发现问题在 fixture 配置上。"""
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = Tupu360Adapter(source(**params), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_both_recruit_types_are_fetched():
    """campus 41 条抓完后不能把 intern 9 条一起终止（内层 if 用 return 而不是 break 的老 bug）。"""
    jobs = run(max_pages=2)
    types = {j.recruit_type for j in jobs}
    assert types == {"campus", "intern"}
    # campus 41 条按 max=15 分 3 页（15/15/11）；max_pages=2 只录了前两页，故 30 条
    assert sum(1 for j in jobs if j.recruit_type == "campus") == 30
    # intern 共 9 条、page_size=5 -> 2 页，两页都录了
    assert sum(1 for j in jobs if j.recruit_type == "intern") == 9


def test_field_mapping_of_real_record():
    j = next(j for j in run(max_pages=2) if "Solution Management" in j.title)
    assert j.company == "西门子"
    # 站点标题是「英文名 中文名」双写，原样保留不切分
    assert j.title == ("Siemens Graduate Program - Solution Management Architecture"
                       " 西门子管理培训生 - 解决方案架构师方向")
    assert j.cities == ["上海", "北京"]
    assert j.department == "工程"
    assert j.publish_at == "2026-10-08"
    assert j.url == ("https://jobs.siemens.com.cn/siemens/position/detail"
                     "?positionId=6aa37e3b7280da28da079988&recruitmentType=CAMPUSRECRUITMENT")


def test_every_job_has_city_and_publish_date():
    """这是全项目里少数「列表就带发布日期」的站，两个字段都不该有空洞。"""
    jobs = run(max_pages=2)
    assert all(j.cities for j in jobs)
    assert all(j.publish_at for j in jobs)


def test_page_two_comes_from_post_offset():
    """第 2 页的岗位必须和第 1 页不重叠；重叠说明 offset 没生效（服务端又返回了第 1 页）。"""
    jobs = run(max_pages=2)
    campus = [j.source_job_id for j in jobs if j.recruit_type == "campus"]
    assert len(campus) == len(set(campus))
    # 第 2 页首条（offset=15 的首个 pid）确实在里面
    assert "6a9fde0c7280da28da0796ba" in campus or "6a9fde107280da28da0796c0" in campus


def test_max_pages_is_respected():
    assert len(run(max_pages=1)) == 15 + 9


def test_detail_page_body_is_stored():
    """列表卡片里没有正文，JD 必须来自详情页 `div.position-description`。

    fixtures 只留了 3 个详情响应（`--keep-details 3`），所以只断言「这几条必须解析出正文」。
    真实的 JD 覆盖率在**全量抓取**里核对（50/50），不靠 fixtures。
    """
    jobs = run(max_pages=2)
    with_jd = [j for j in jobs if (j.description or "").strip()]
    assert len(with_jd) == 3
    body = with_jd[0].description
    assert "Why Choose Us" in body
    # 详情页的 <div>/<br> 换成换行，不能连成一大坨
    assert "\n" in body
    assert len(body) > 200


def test_field_and_job_id_helpers():
    rest = ('<li class="ele"><span class="txt">工作地点：上海,北京</span></li>'
            '<li class="ele"><span class="txt">JobID:522053</span></li>')
    assert _field(rest, "工作地点") == "上海,北京"
    assert _field(rest, "职能类别") is None
    assert _job_id(rest) == "522053"
