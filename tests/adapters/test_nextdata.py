"""Next.js 招聘页（`__NEXT_DATA__` 内嵌 JSON）契约测试。

被测站：豆瓣阅读 `careers.arkread.com` —— 2026-10-27 由「官网 → 招聘入口」扫描发现，
岗位全在 `<script id="__NEXT_DATA__">` 里，`props.pageProps.jobList[*].content`
按「职位描述 / 职位要求 / 优先条件」分组。

两个必须守住的点：
  1. 分组必须按中文名归到职责/要求两侧（「优先条件」属于要求，不是职责）；
  2. **不能按 `isOpen` 过滤**——该字段在真实数据里 24 个岗位有 22 个是 false，
     但正文齐全、页面照常展示，按它过滤会把整站岗丢光。
"""
from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.nextdata import NextdataAdapter, dig
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "nextdata"


def source(**params) -> SourceConfig:
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data["params"], **params}
    return SourceConfig(**data)


def run(src: SourceConfig | None = None, transport=None) -> list:
    a = NextdataAdapter(src or source(),
                        httpx.Client(transport=transport or ReplayTransport(FX)),
                        sleep=lambda s: None)
    return list(a.fetch_all())


def test_jobs_come_from_embedded_json():
    jobs = run()
    assert len(jobs) == 3
    assert [j.title for j in jobs][:2] == ["版权经理", "产品运营"]


def test_description_and_requirements_are_split():
    j = next(j for j in run() if j.source_job_id == "copyright-manager")
    assert j.company == "豆瓣阅读"
    assert j.description.startswith("负责电子书版权的引入")
    assert j.requirements.startswith("应届或往届本科及以上学历")


def test_priority_conditions_go_to_requirements():
    """「优先条件」是要求侧的补充，不能混进职责。"""
    j = next(j for j in run() if j.source_job_id == "product-operations")
    assert "优先条件" not in (j.description or "")
    assert j.requirements.count("\n") >= 1


def test_closed_flag_does_not_drop_jobs():
    """isOpen=false 的岗位照样收（真实站点 24 个里 22 个是 false，过滤就丢光）。"""
    assert all(j.description for j in run())


def test_drop_closed_is_opt_in():
    src = source(drop_closed=True)
    assert run(src) == []


def test_missing_next_data_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>改版了</body></html>")

    with pytest.raises(RuntimeError, match="__NEXT_DATA__"):
        run(transport=httpx.MockTransport(handler))


def test_dig_handles_bad_paths():
    assert dig({"a": {"b": [1, {"c": 2}]}}, "a.b.1.c") == 2
    assert dig({"a": 1}, "a.b.c") is None
    assert dig({"a": [0]}, "a.5") is None
