"""深信服（`hr.sangfor.com`）：Nuxt SPA + 匿名 Bearer token 的 WebAPI。

三个坑都在 2026-10-27 实测过，缺一个就全盘 404/401/415：
  1. token 必须从 `/webapi/api/connect/token` 取（去掉 `webapi` 前缀就是 404）；
  2. 列表必须带 `X-Requested-With: XMLHttpRequest`（缺了 404）；
  3. `Content-Type` 必须是 `application/json`（`text/plain` 415，而前端 axios 默认恰恰是 text/plain）。
另外 `channelId` 要传 **0** 才是全渠道；`100`/`101` 都只返回 31 条校招。
"""

from pathlib import Path

import httpx
import yaml

from jobradar.adapters.recording import ReplayTransport
from jobradar.adapters.sangfor import SangforAdapter
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "sangfor"


def _source() -> SourceConfig:
    return SourceConfig(**yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8")))


def test_replay_real_records():
    with httpx.Client(transport=ReplayTransport(FX), timeout=5.0) as c:
        jobs = list(SangforAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    # fixtures 用 max_pages 限了一页（page_size 100），实测第一页 40 条含实习/校招/社招
    assert len(jobs) >= 20
    assert all(j.description for j in jobs), "深信服的 JD 全文就在列表里，不该有空正文"


def test_replay_splits_duty_and_requirement():
    with httpx.Client(transport=ReplayTransport(FX), timeout=5.0) as c:
        jobs = list(SangforAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    with_req = [j for j in jobs if j.requirements]
    assert with_req, "深信服的 JD 里带「岗位要求：」，必须切出要求段"
    # 「岗位要求」这个词不该留在职责里
    assert all("岗位要求" not in (j.description or "") for j in jobs)


def test_replay_types_and_cities():
    with httpx.Client(transport=ReplayTransport(FX), timeout=5.0) as c:
        jobs = list(SangforAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    kinds = {j.recruit_type for j in jobs}
    assert kinds <= {"campus", "intern", "social"}
    multi = [j for j in jobs if len(j.cities) >= 2]
    assert multi, "workPlaceText 是逗号串，必须拆成多个城市"


def test_token_and_list_headers():
    """token 请求与列表请求的头契约：少一个就是 404/401/415。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/connect/token"):
            return httpx.Response(200, json={"access_token": "T"})
        return httpx.Response(200, json={"code": 0, "data": {"count": 0, "listData": []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        list(SangforAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    token_req = seen[0]
    assert token_req.url.path == "/webapi/api/connect/token"
    assert token_req.headers["x-requested-with"] == "XMLHttpRequest"
    jobs_req = seen[1]
    assert jobs_req.url.path == "/webapi/api/Jobs"
    assert jobs_req.headers["authorization"] == "Bearer T"
    assert jobs_req.headers["content-type"] == "application/json"
    assert b'"channelId": 0' in jobs_req.content or b'"channelId":0' in jobs_req.content
