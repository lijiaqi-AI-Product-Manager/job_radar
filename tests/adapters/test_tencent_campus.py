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
