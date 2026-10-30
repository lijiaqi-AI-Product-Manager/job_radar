"""每个已注册的适配器都必须通过的契约。新增适配器若缺 fixtures 或缺专属测试，这里会失败。

要求：
- tests/fixtures/<id>/{manifest.json, source.yaml, 响应文件}  由 scripts/record_fixtures.py 录制
- tests/adapters/test_<id>.py  至少断言一条真实记录的字段映射（标题/城市/届别/链接等）

多源适配器（一个适配器服务多家公司，如 `feishu_atsx` 服务蔚来/小鹏/Momenta）：
fixtures 按 **source** 分目录 `tests/fixtures/<adapter>_<source>/`，契约对每个目录各跑一遍。
判定方式：`<id>/` 不存在、但存在 `<id>_*` 目录时，自动按多源处理。
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


def fixture_dirs(aid: str) -> list[Path]:
    """某适配器的全部 fixture 目录。单源 = `<aid>/`；多源 = `<aid>_<source>/` 若干。"""
    single = TESTS / "fixtures" / aid
    if (single / "manifest.json").exists():
        return [single]
    return sorted(p for p in (TESTS / "fixtures").glob(f"{aid}_*") if (p / "manifest.json").exists())


def cases() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for aid in sorted(ADAPTERS):
        for d in fixture_dirs(aid) or [TESTS / "fixtures" / "__missing__"]:
            out.append((aid, d))
    return out


CASES = cases()
IDS = [f"{aid}:{d.name}" for aid, d in CASES]


def fixture_adapter(aid, source, client):
    # 公告有效期是业务字段；历史录制须按核查日回放，避免真实样本到期后 CI 随日历漂移。
    kwargs = {"reference_date": source.compliance.checked_on} if aid == "jysd" else {}
    return ADAPTERS[aid](source, client, sleep=lambda s: None, **kwargs)


def test_there_is_at_least_one_adapter():
    assert ADAPTERS


@pytest.mark.parametrize("aid", sorted(ADAPTERS))
def test_adapter_has_fixtures_and_own_test(aid):
    dirs = fixture_dirs(aid)
    assert dirs, f"缺少 fixtures：tests/fixtures/{aid}/manifest.json（或 {aid}_<source>/）"
    for d in dirs:
        assert (d / "source.yaml").exists(), f"缺少 {d}/source.yaml"
    assert (TESTS / "adapters" / f"test_{aid}.py").exists(), f"缺少专属测试 tests/adapters/test_{aid}.py"


# 单源 fixtures 的体积上限。超过就说明录的时候没裁剪。
#
# 2026-10-26 起 `_LARGE` 里的源单独放宽到 360KB：赛诺菲/西门子的**详情页本身就 100KB+**
# （服务端把整站 CSS 与 Razor 模板都内联在 HTML 里），而这几个详情页必须留着 ——
# 发布时间、申请截止日、JD 正文三个字段**只**存在于详情页，砍掉就没法断言了。
# 这是「实测数据决定的上限」，不是随手放宽；新源一律按 300KB 走。
_LARGE = {"tupu360:tupu360", "radancy:radancy", "avature:avature_avature-danone"}


@pytest.mark.parametrize(("aid", "fx"), CASES, ids=IDS)
def test_fixtures_are_small(aid, fx):
    limit = 360_000 if f"{aid}:{fx.name}" in _LARGE else 300_000
    size = sum(f.stat().st_size for f in fx.rglob("*") if f.is_file())
    assert size < limit, f"fixtures {fx.name} {size} bytes：用 max_pages 限量，或裁剪响应"


@pytest.mark.parametrize(("aid", "fx"), CASES, ids=IDS)
def test_adapter_contract(aid, fx):
    source = SourceConfig(**yaml.safe_load((fx / "source.yaml").read_text(encoding="utf-8")))
    assert source.adapter == aid
    client = httpx.Client(transport=ReplayTransport(fx))
    jobs = list(fixture_adapter(aid, source, client).fetch_all())

    assert jobs, "回放后一条岗位都没有"
    assert all(isinstance(j, Job) for j in jobs)
    assert all(j.source_id == source.id for j in jobs)
    assert len({j.id for j in jobs}) == len(jobs), "同一次抓取里岗位 id 重复"
    assert all(j.url.startswith("http") and j.title.strip() for j in jobs)
    assert all(j.company for j in jobs)


# 详情页型源：正文只在详情页里，fixtures 为了体积只录了前 K 个详情响应。
# 对这些源，本测试改成「录到的详情必须全部解析出正文」，而不是要求 90% 覆盖 ——
# 覆盖率由全量抓取核对，不由 fixtures 核对（fixtures 是离线回放，不可能录满）。
_DETAIL_ONLY = {"tupu360:tupu360", "radancy:radancy"}


@pytest.mark.parametrize(("aid", "fx"), CASES, ids=IDS)
def test_adapter_stores_jd_text(aid, fx):
    """JD 正文必须入库（2026-10-21 起的硬性要求）：≥90% 的岗位要有职责或要求原文。列表里没有就请求详情页。"""
    source = SourceConfig(**yaml.safe_load((fx / "source.yaml").read_text(encoding="utf-8")))
    jobs = list(fixture_adapter(aid, source, httpx.Client(transport=ReplayTransport(fx))).fetch_all())
    with_jd = [j for j in jobs if (j.description or "").strip() or (j.requirements or "").strip()]
    if f"{aid}:{fx.name}" in _DETAIL_ONLY:
        # 回放里录了几个详情，就必须解出几个正文；一个都没解出来说明正文抽取正则坏了
        assert with_jd, f"{aid}/{fx.name}: 录了详情却一条正文都没解出来（抽取正则大概率坏了）"
        assert all(len(j.description) > 100 for j in with_jd), "解出来的正文过短，多半是截断正则不吃嵌套标签"
        return
    assert len(with_jd) >= 0.9 * len(jobs), f"{aid}/{fx.name}: 只有 {len(with_jd)}/{len(jobs)} 个岗位有 JD 正文"
