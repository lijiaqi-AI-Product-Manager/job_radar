from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.alibaba import AlibabaAdapter
from jobradar.adapters.base import SkipRecord
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "alibaba"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = AlibabaAdapter(source(**params), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    j = next(j for j in run() if j.source_job_id == "199907740040")
    assert j.id == "alibaba:199907740040"
    assert j.company == "阿里巴巴"
    assert j.title == "AI应用算法工程师"
    assert j.recruit_type == "campus"
    assert j.grad_year == 2027  # 批次名「阿里巴巴2027届应届生」
    assert j.cities == ["北京", "广州", "杭州", "上海"]
    assert j.department.startswith("阿里巴巴控股集团 / 淘天集团")
    assert j.url == "https://campus-talent.alibaba.com/campus/position/199907740040"
    assert j.description.startswith("将大模型能力做成可上线")
    assert j.requirements.startswith("1.基础条件")


def test_intern_batches_are_intern_without_grad_year():
    # 「阿里巴巴日常实习生」「研究型实习生」批次名没写届别：留空，不猜
    jobs = run()
    interns = [j for j in jobs if j.recruit_type == "intern"]
    assert interns
    assert all(j.grad_year is None for j in interns)
    assert all(j.recruit_type == "campus" and j.grad_year == 2027
               for j in jobs if j.recruit_type == "campus")


def test_every_job_has_jd_text():
    jobs = run()
    assert len(jobs) == 9
    assert all(j.description and j.requirements for j in jobs)


def test_batch_repeated_across_groups_is_fetched_once():
    # 「阿里星-27届应届生」与应届生批次是同一个 batchId：只抓一次，岗位不重复
    ids = [j.source_job_id for j in run()]
    assert len(ids) == len(set(ids)) == 9


def test_missing_token_fails_loudly():
    a = AlibabaAdapter(source(), httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html>no token here</html>"))), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="token not found"):
        list(a.fetch_all())


def test_http_error_message_does_not_leak_token():
    """异常信息会进健康报告和 issue：token 不能出现在里面（docs/DEVELOPMENT.md 铁律 1）。"""
    secret = "TOKEN-SHOULD-NOT-LEAK"
    page = f'<script>window.__sysconfig = {{__token__: "{secret}"}}</script>'

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text=page)
        return httpx.Response(403, json={"success": False})

    a = AlibabaAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError) as ei:
        list(a.fetch_all())
    assert secret not in str(ei.value)
    assert "403" in str(ei.value)


def test_unusable_record_is_skipped():
    a = AlibabaAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({"id": 1, "_recruit_type": "campus"},                  # 缺标题
                {"name": "算法", "_recruit_type": "campus"},           # 缺 id
                {"id": 2, "name": "算法", "_recruit_type": "social"},  # 类型不支持
                {"id": 3, "name": "算法"}):                            # 缺批次类型
        with pytest.raises(SkipRecord):
            a.normalize(raw)
