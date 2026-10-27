from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.baidu import BaiduAdapter
from jobradar.adapters.base import SkipRecord
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "baidu"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    adapter = BaiduAdapter(source(**params), httpx.Client(transport=ReplayTransport(FX)),
                           sleep=lambda s: None)
    return list(adapter.fetch_all())


def test_field_mapping_of_real_record():
    j = run()[0]
    # 校招那条：标题自带城市前缀和职位编号
    assert j.source_id == "baidu"
    assert j.company == "百度"
    assert j.title == "北京-网络研发工程师(J100700)"
    assert j.recruit_type == "campus"
    assert j.cities == ["北京"]
    assert j.publish_at == "2026-07-08"          # 直接用接口给的 publishDate
    assert j.category is None                    # postType="技术" 不进 category，保持与其它源自洽
    assert j.url == "https://talent.baidu.com/jobs/detail/545e6823-28d2-4cb5-aba2-3c520a31b4e0?recruitType=GRADUATE"
    assert j.description and j.requirements


def test_both_recruit_types_and_both_pages_are_fetched():
    jobs = run()
    assert len(jobs) == 40                       # 2 类型 × 2 页 × 10 条
    assert {j.recruit_type for j in jobs} == {"campus", "intern"}
    # 曾经的 bug：空页写 return，配了 campus + intern 时只抓到第一个类型
    # 更早的 bug：分页参数放在 body 里被服务端静默忽略，16 次"翻页"拿到同一页
    assert len({j.source_job_id for j in jobs}) == 40


def test_pagination_params_must_be_in_query_not_body():
    """`curPage`/`pageSize` 放 body 里服务端会静默忽略，一直返回第 1 页——2026-10-26 真实踩过。

    这条测试直接检查请求形状：分页必须在 query，body 里只留 recruitType。
    """
    seen = []

    def handler(request):
        seen.append((str(request.url), request.content.decode()))
        return httpx.Response(200, json={"status": "ok", "data": {"total": "1", "list": [
            {"postId": "p1", "name": "岗位", "projectType": "校招"}]}})

    s = source()
    s.params = {}
    a = BaiduAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    list(a.fetch_all())
    for url, body in seen:
        assert "curPage=" in url and "pageSize=" in url
        assert "curPage" not in body and "pageSize" not in body
        assert "recruitType" in body          # body 里仍要带，否则 Illegal argument


def test_page_size_is_always_ten():
    """服务端只接受 pageSize=10，写 50 会得到 `Illegal argument : pageSize`。"""
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"status": "ok", "data": {"total": "0", "list": []}})

    s = source()
    s.params = {"page_size": 50}              # 就算配了别的值也不该生效
    a = BaiduAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    list(a.fetch_all())
    assert urls and all("pageSize=10" in u for u in urls)


def test_repeated_page_stops_instead_of_looping():
    """分页失效时服务端会重复返回同一页；必须靠 postId 去重发现自己没前进并停下。"""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"status": "ok", "data": {"total": "999", "list": [
            {"postId": "same-1", "name": "岗位A"}, {"postId": "same-2", "name": "岗位B"}]}})

    s = source()
    s.params = {}                              # 不设 max_pages，全靠自检兜住
    a = BaiduAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    jobs = list(a.fetch_all())
    assert len(jobs) == 4                      # 两种类型各 2 条，没有把同一页刷 50 次
    assert len(calls) == 4                     # 每种类型：第 1 页 + 第 2 页（发现重复后停）


def test_multi_city_workplace_is_split():
    multi = [j for j in run() if len(j.cities) > 1]
    assert multi, "应有多城市岗位"
    assert all(c in {"北京", "上海", "深圳", "杭州", "广州", "成都"} for j in multi for c in j.cities)


def test_intern_batch_is_not_inferred():
    intern = next(j for j in run() if j.recruit_type == "intern")
    assert intern.batch is None


def test_missing_id_or_title_is_skipped():
    a = BaiduAdapter(source(), httpx.Client(), sleep=lambda s: None)
    for raw in ({"postId": "", "name": "x", "_recruit_type": "campus", "_code": "GRADUATE"},
                {"postId": "1", "name": "  ", "_recruit_type": "campus", "_code": "GRADUATE"},
                {"name": "x", "_recruit_type": "campus", "_code": "GRADUATE"}):
        with pytest.raises(SkipRecord):
            a.normalize(raw)


def test_referer_is_sent_on_every_page():
    """缺 Referer 时接口返回 {"status":"no-auth","message":"illegal-visit"}——2026-10-26 实测踩过。"""
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("referer")))
        return httpx.Response(200, json={"status": "ok", "data": {"total": "0", "list": []}})

    s = source()
    s.params = {}
    a = BaiduAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    list(a.fetch_all())
    assert len(seen) == 2
    assert all(ref for _url, ref in seen)
    # Referer 必须和本请求的 recruitType 对得上（列表页就是按类型切的）
    assert seen[0][1].endswith("recruitType=GRADUATE")
    assert seen[1][1].endswith("recruitType=INTERN")


def test_non_ok_status_raises():
    def handler(request):
        return httpx.Response(200, json={"status": "no-auth", "message": "illegal-visit"})

    a = BaiduAdapter(source(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="illegal-visit"):
        list(a.fetch_all())


def test_empty_first_page_still_tries_next_recruit_type():
    """空页只能结束当前类型，不能结束整个生成器。"""
    def handler(request):
        if "recruitType=GRADUATE" in str(request.url):
            return httpx.Response(200, json={"status": "ok", "data": {"total": "0", "list": []}})
        return httpx.Response(200, json={"status": "ok", "data": {"total": "1", "list": [
            {"postId": "p9", "name": "实习岗", "projectType": "日常实习"}]}})

    s = source()
    s.params = {}
    a = BaiduAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    jobs = list(a.fetch_all())
    assert [j.recruit_type for j in jobs] == ["intern"]
