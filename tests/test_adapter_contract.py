"""每个已注册的适配器都必须通过的契约。新增适配器若缺 fixtures 或缺专属测试，这里会失败。

要求：
- tests/fixtures/<id>/{manifest.json, source.yaml, 响应文件}  由 scripts/record_fixtures.py 录制
- tests/adapters/test_<id>.py  至少断言一条真实记录的字段映射（标题/城市/届别/链接等）
"""

from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import load_all
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import Job, SourceConfig

TESTS = Path(__file__).parent
ADAPTERS = load_all()


def test_there_is_at_least_one_adapter():
    assert ADAPTERS


@pytest.mark.parametrize("aid", sorted(ADAPTERS))
def test_adapter_has_fixtures_and_own_test(aid):
    fx = TESTS / "fixtures" / aid
    assert (fx / "manifest.json").exists(), f"缺少 fixtures：tests/fixtures/{aid}/manifest.json"
    assert (fx / "source.yaml").exists(), f"缺少 tests/fixtures/{aid}/source.yaml"
    assert (TESTS / "adapters" / f"test_{aid}.py").exists(), f"缺少专属测试 tests/adapters/test_{aid}.py"


@pytest.mark.parametrize("aid", sorted(ADAPTERS))
def test_fixtures_are_small(aid):
    size = sum(f.stat().st_size for f in (TESTS / "fixtures" / aid).rglob("*") if f.is_file())
    assert size < 300_000, f"fixtures {size} bytes：用 max_pages 限量，或裁剪响应"


@pytest.mark.parametrize("aid", sorted(ADAPTERS))
def test_adapter_contract(aid):
    fx = TESTS / "fixtures" / aid
    source = SourceConfig(**yaml.safe_load((fx / "source.yaml").read_text(encoding="utf-8")))
    assert source.adapter == aid
    client = httpx.Client(transport=ReplayTransport(fx))
    jobs = list(ADAPTERS[aid](source, client, sleep=lambda s: None).fetch_all())

    assert jobs, "回放后一条岗位都没有"
    assert all(isinstance(j, Job) for j in jobs)
    assert all(j.source_id == source.id for j in jobs)
    assert len({j.id for j in jobs}) == len(jobs), "同一次抓取里岗位 id 重复"
    assert all(j.url.startswith("http") and j.title.strip() for j in jobs)
    assert all(j.company for j in jobs)


@pytest.mark.parametrize("aid", sorted(ADAPTERS))
def test_adapter_stores_jd_text(aid):
    """JD 正文必须入库（2026-10-21 起的硬性要求）：≥90% 的岗位要有职责或要求原文。列表里没有就请求详情页。"""
    fx = TESTS / "fixtures" / aid
    source = SourceConfig(**yaml.safe_load((fx / "source.yaml").read_text(encoding="utf-8")))
    jobs = list(ADAPTERS[aid](source, httpx.Client(transport=ReplayTransport(fx)), sleep=lambda s: None).fetch_all())
    with_jd = [j for j in jobs if (j.description or "").strip() or (j.requirements or "").strip()]
    assert len(with_jd) >= 0.9 * len(jobs), f"{aid}: 只有 {len(with_jd)}/{len(jobs)} 个岗位有 JD 正文"
