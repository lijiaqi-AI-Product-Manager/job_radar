from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.recording import ReplayTransport
from jobradar.adapters.tencent_campus import TencentCampusAdapter, recruit_type_of
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "tencent_campus"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run():
    a = TencentCampusAdapter(source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    j = next(j for j in run() if j.source_job_id == "1282707398326592512")
    assert j.id == "tencent-campus:1282707398326592512"
    assert j.company == "腾讯"
    assert j.title == "AI全栈工程师"
    assert j.recruit_type == "campus"
    assert j.cities == ["深圳", "北京", "上海", "广州", "成都", "杭州"]  # "深圳总部"→深圳
    assert j.department == "CDG CSIG IEG PCG TEG WXG"
    assert j.url == "https://join.qq.com/post_detail.html?postid=1282707398326592512"
    assert j.description.startswith("1、负责产品业务系统的全栈开发")
    assert j.requirements.startswith("1、熟练掌握主流前后端技术栈")


def test_each_job_gets_its_detail():
    jobs = run()
    assert len(jobs) == 5
    assert all(j.description and j.requirements for j in jobs)


@pytest.mark.parametrize("project,rtype", [
    ("应届毕业生", "campus"), ("青云计划-应届生", "campus"), ("应届实习", "intern"),
    ("项目实习生", "intern"), ("日常实习", "intern"), ("", None), ("社会招聘", None),
])
def test_recruit_type_of(project, rtype):
    assert recruit_type_of(project) == rtype


def test_incomplete_or_unknown_project_is_skipped():
    a = TencentCampusAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({"postId": "1", "positionTitle": "x", "projectName": "其他"},
                {"postId": "", "positionTitle": "x", "projectName": "应届毕业生"},
                {"postId": "1", "projectName": "应届毕业生"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)


def test_failed_detail_status_leaves_jd_empty():
    def handler(request):
        if "searchPosition" in str(request.url):
            return httpx.Response(200, json={"status": 0, "data": {"count": 1, "positionList": [
                {"postId": "9", "positionTitle": "后台开发", "projectName": "应届实习", "workCities": "北京 "}]}})
        return httpx.Response(200, json={"status": 1, "message": "not found"})

    a = TencentCampusAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    [j] = a.fetch_all()
    assert j.recruit_type == "intern" and j.cities == ["北京"] and j.description is None


def _one_job_client(detail: dict, project="青云计划-应届生"):
    def handler(request):
        if "searchPosition" in str(request.url):
            return httpx.Response(200, json={"status": 0, "data": {"count": 1, "positionList": [
                {"postId": "1274356447064759296", "positionTitle": "腾讯营销—基于大模型Agent的腾讯电商广告推荐研究",
                 "projectName": project, "workCities": "上海 "}]}})
        return httpx.Response(200, json=detail)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_qingyun_topic_uses_topic_detail_and_requirement():
    # 青云课题岗位的 desc/request 为空，JD 在 topicDetail/topicRequirement（2026-10-21 详情接口实测，节选）
    detail = {"status": 0, "message": "", "data": {
        "postId": "1274356447064759296", "tidName": "青云课题", "desc": "", "request": "", "introduction": "",
        "topicDetail": "课题背景：\n微信小店作为交易闭环的核心阵地……\n工作内容：\n1. 负责腾讯电商营销全链路推荐和排序优化",
        "topicRequirement": "1、硕士研究生及以上学历，计算机科学、人工智能、自然语言处理、多模态等相关领域；"}}
    a = TencentCampusAdapter(source(), _one_job_client(detail), sleep=lambda s: None)
    [j] = a.fetch_all()
    assert j.description.startswith("课题背景：")
    assert j.requirements.startswith("1、硕士研究生及以上学历")


def test_delisted_post_is_skipped():
    # 列表仍返回、但详情明确"岗位已下架"的岗位不入库
    detail = {"status": 404, "message": "岗位已下架", "data": None}
    a = TencentCampusAdapter(source(), _one_job_client(detail), sleep=lambda s: None)
    assert list(a.fetch_all()) == []
