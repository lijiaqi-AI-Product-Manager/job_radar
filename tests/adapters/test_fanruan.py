"""帆软招聘站适配器：WordPress 主题自带分页 JSON。

2026-10-27 实测：`POST https://join.fanruan.com/{social|campus|trainee}`（URL 不变），
带 `X-Requested-With: XMLHttpRequest` + 同 URL 的 Referer 才回 JSON，否则回整页 HTML。
列表直接给 `duty` / `requirement` 全文，不需要详情页。
"""

from pathlib import Path

import httpx
import yaml

from jobradar.adapters.fanruan import FanruanAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "fanruan"


def _source(**params) -> SourceConfig:
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def test_replay_real_records():
    with httpx.Client(transport=ReplayTransport(FX), timeout=5.0) as c:
        jobs = list(FanruanAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    # fixtures 只录了三个列表的第一页（social 10 + campus 10 + trainee 8 = 28）
    assert len(jobs) == 28
    assert all(j.description for j in jobs), "列表接口自带职责，不该有空正文"
    assert all(j.requirements for j in jobs), "列表接口自带要求，不该有空正文"


def test_replay_cities_split_and_types():
    with httpx.Client(transport=ReplayTransport(FX), timeout=5.0) as c:
        jobs = list(FanruanAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    # `base` 是「无锡, 南京」这种逗号串，必须拆成多个城市
    multi = [j for j in jobs if len(j.cities) >= 2]
    assert multi, "至少有一条岗位是跨城市的（帆软无锡/南京双基地）"
    kinds = {j.recruit_type for j in jobs}
    assert kinds <= {"campus", "intern", "social"}
    assert "social" in kinds


def test_headers_contract():
    """缺 `X-Requested-With` 就回 HTML；Referer 必须与请求 URL 一致。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"list": [], "pageTotal": 1, "dataTotal": "0"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        list(FanruanAdapter(_source(paths=["social"]), c, sleep=lambda s: None).fetch_all())
    assert seen, "一次请求都没发"
    req = seen[0]
    assert req.method == "POST"
    assert req.headers["x-requested-with"] == "XMLHttpRequest"
    assert req.headers["referer"] == "https://join.fanruan.com/social"
    assert str(req.url) == "https://join.fanruan.com/social"
