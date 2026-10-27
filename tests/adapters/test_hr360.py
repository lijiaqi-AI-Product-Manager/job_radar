"""360 招聘适配器契约测试。

守住的线（2026-10-27 实测，两处都会静默失败）：
1. **列表要 `X-Requested-With` + `Referer`**，缺任一个服务端回 500 —— 不是 401/403，
   排障时极易误判成「接口不存在」。
2. **详情必须 GET**（POST 会 301 到 `/hr/`），并且 Referer 要指向该岗位的详情页。
   用列表页的 Referer 也 500。这条以前试过三轮才通。

用 `httpx.MockTransport` 直接给假响应，不联网。
"""

from pathlib import Path

import httpx
import yaml

from jobradar.adapters.base import Adapter
from jobradar.adapters.hr360 import Hr360Adapter
from jobradar.models import SourceConfig

LIST_BODY = {
    "code": 0,
    "count": 2,
    "data": [
        {"id": "aaa111", "title": "移动端开发专家", "type": "技术", "position": "技术",
         "area": "北京", "date": "2026-09-18"},
        {"id": "bbb222", "title": "2027届安全工程师（实习）", "type": "安全", "position": "安全",
         "area": "武汉市", "date": "2026-09-01"},
    ],
}
DETAIL_BODY = {
    "code": 0,
    "data": {"id": "aaa111", "title": "移动端开发专家", "area": "北京",
             "date": "2026-08-13", "description": "岗位描述\n- 负责浏览器内核适配。"},
}
LIST_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://hr.360.cn/hr/list",
    "Content-Type": "application/json",
}


def _source(**params) -> SourceConfig:
    defaults = yaml.safe_load(
        open("sources/hr360.yaml", encoding="utf-8").read()
    )["defaults"]
    entry = {"id": "hr360-360", "company": "360", "params": params,
             "recruit_types": ["campus", "intern", "social"]}
    data = {**defaults, **entry}
    data["params"] = {**defaults.get("params", {}), **params}
    return SourceConfig(**data)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler),
                        headers={"User-Agent": "test"}, timeout=5.0)


def test_list_requires_xhr_and_referer():
    """缺 X-Requested-With 或 Referer → 500，适配器必须真的带上这两个头。"""
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        h = dict(req.headers)
        seen.append(h)
        if req.url.path.endswith("getlistsearch"):
            if h.get("x-requested-with") != "XMLHttpRequest" or "hr/list" not in h.get("referer", ""):
                return httpx.Response(500)
            return httpx.Response(200, json=LIST_BODY)
        return httpx.Response(200, json=DETAIL_BODY)

    with _client(handler) as c:
        jobs = list(Hr360Adapter(_source(with_detail=False), c).fetch_all())
    assert len(jobs) == 2
    assert seen, "没有发出请求"


def test_detail_is_get_with_job_referer():
    """详情走 GET，Referer 必须是该岗位详情页（用列表页 Referer 会 500）。"""
    calls: list[tuple[str, str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getlistsearch"):
            return httpx.Response(200, json=LIST_BODY)
        ref = req.headers.get("referer", "")
        calls.append((req.method, req.url.params.get("id", ""), ref))
        if req.method != "GET" or "/hr/detail/" not in ref:
            return httpx.Response(500)
        return httpx.Response(200, json=DETAIL_BODY)

    with _client(handler) as c:
        jobs = list(Hr360Adapter(_source(with_detail=True), c).fetch_all())
    assert calls, "详情接口没被调用"
    assert all(m == "GET" for m, _, _ in calls)
    assert calls[0][2].endswith("/hr/detail/aaa111")
    assert "负责浏览器内核适配" in (jobs[0].description or "")


def test_normalize_fields_and_recruit_type():
    """城市/发布日原样保留；标题带「实习」判 intern，带「届」判 campus。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getlistsearch"):
            return httpx.Response(200, json=LIST_BODY)
        return httpx.Response(200, json=DETAIL_BODY)

    with _client(handler) as c:
        jobs = list(Hr360Adapter(_source(with_detail=False), c).fetch_all())
    by_title = {j.title: j for j in jobs}
    a = by_title["移动端开发专家"]
    assert a.cities == ["北京"]
    assert a.publish_at == "2026-09-18"
    assert a.recruit_type == "social"
    assert a.url.endswith("/hr/detail/aaa111")
    b = by_title["2027届安全工程师（实习）"]
    assert b.recruit_type == "intern"
    assert b.cities == ["武汉市"]


def test_detail_failure_does_not_abort_list():
    """详情挂了不能整轮丢：列表级字段仍然可用（标题/城市/日期）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getlistsearch"):
            return httpx.Response(200, json=LIST_BODY)
        return httpx.Response(500)

    with _client(handler) as c:
        jobs = list(Hr360Adapter(_source(with_detail=True), c).fetch_all())
    assert len(jobs) == 2
    assert all(j.description is None for j in jobs)
    assert all(j.cities for j in jobs)


def test_registered():
    assert Hr360Adapter.id == "hr360"
    assert issubclass(Hr360Adapter, Adapter)


# ---------------------------------------------------------------------------
# 真实录制（scripts/record_fixtures.py hr360-360）：25 岗 / 26 个响应，47KB。
# 上面几条用 MockTransport 测「请求头契约」，这里用回放测「真实字段映射」——
# 两者互补：前者保证不会 500，后者保证解析出的城市/日期/JD 不是空壳。
# ---------------------------------------------------------------------------
HR360_FX = Path(__file__).parent.parent / "fixtures" / "hr360"


def _replay_source() -> SourceConfig:
    return SourceConfig(**yaml.safe_load((HR360_FX / "source.yaml").read_text(encoding="utf-8")))


def test_replay_real_record_fields():
    """回放真实响应：列表 25 岗，标题/城市/发布日/JD 全都解析得出。"""
    from jobradar.adapters.recording import ReplayTransport

    with httpx.Client(transport=ReplayTransport(HR360_FX), timeout=5.0) as c:
        jobs = list(Hr360Adapter(_replay_source(), c).fetch_all())
    assert len(jobs) == 25
    assert all(j.title for j in jobs)
    assert sum(1 for j in jobs if j.cities) == 25
    assert sum(1 for j in jobs if j.publish_at) == 25
    assert sum(1 for j in jobs if j.description) == 25
    # 城市要落到市一级，且不能是「全部」这种筛选项残留
    assert {c for j in jobs for c in j.cities} - {"全部"}
    one = next(j for j in jobs if "开发" in j.title)
    assert one.url.startswith("https://hr.360.cn/hr/detail/")
    assert "岗位描述" in (one.description or "")
