from pathlib import Path

import pytest
from pydantic import ValidationError

from jobradar.adapters.base import load_all
from jobradar.models import SourceConfig
from jobradar.sources import load_sources, parse_file

SOURCES = Path(__file__).parent.parent / "sources"


def test_all_sources_are_valid_and_unique():
    srcs = load_sources(SOURCES)
    ids = [s.id for s in srcs]
    assert len(ids) == len(set(ids)), "source id 重复"
    adapters = load_all(include_drafts=True)  # 草稿适配器的源可以先登记
    for s in srcs:
        assert s.adapter in adapters, f"{s.id}: 未知适配器 {s.adapter}"
        assert s.enabled is False or s.compliance is not None


def test_example_file_parses():
    srcs = load_sources(SOURCES, include_examples=True)
    assert any(s.id.startswith("moka-demo") for s in srcs)


def test_enabled_source_requires_compliance():
    with pytest.raises(ValidationError):
        SourceConfig(id="x", company="X", adapter="a")
    SourceConfig(id="x", company="X", adapter="a", enabled=False)


def test_batch_file_merges_defaults(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "defaults:\n  adapter: moka\n  params: {site: campus}\n"
        "  compliance: {checked_on: 2026-10-20, robots: allowed, terms: ok}\n"
        "sources:\n  - {id: moka-a, company: A, params: {org: a}}\n"
        "  - {id: moka-b, company: B, params: {org: b}, recruit_types: [intern]}\n"
    )
    a, b = parse_file(p)
    assert a.params == {"site": "campus", "org": "a"} and a.recruit_types == ["campus"]
    assert b.recruit_types == ["intern"] and b.compliance.robots == "allowed"
def test_unknown_top_level_field_is_rejected(tmp_path):
    """顶格写 max_pages 曾经静默失效（限额不生效，星巴克一次抓了 1.8 万岗）——现在必须报错。"""
    p = tmp_path / "bad.yaml"
    p.write_text(
        "defaults: {adapter: beisen, compliance: {checked_on: 2026-10-20, robots: allowed, terms: t}}\n"
        "sources:\n"
        "  - {id: bad-1, company: 某公司, params: {tenant: x}, max_pages: 3}\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="params"):
        load_sources(tmp_path)


def test_max_pages_inside_params_works(tmp_path):
    p = tmp_path / "ok.yaml"
    p.write_text(
        "defaults: {adapter: beisen, compliance: {checked_on: 2026-10-20, robots: allowed, terms: t}}\n"
        "sources:\n"
        "  - {id: ok-1, company: 某公司, params: {tenant: x, max_pages: 3}}\n",
        encoding="utf-8")
    (s,) = load_sources(tmp_path)
    assert s.max_pages == 3


def test_source_kind_is_typed_and_defaults_to_official():
    assert SourceConfig(id="official", company="A", adapter="example", enabled=False).source_kind == "official"
    assert SourceConfig(id="third-party", company="A", adapter="new_channel", enabled=False,
                        source_kind="aggregator").source_kind == "aggregator"
    with pytest.raises(ValidationError):
        SourceConfig(id="bad-kind", company="A", adapter="example", enabled=False, source_kind="guess")


def test_existing_aggregator_sources_are_explicitly_classified():
    for filename in ("shixiseng.yaml", "campus.yaml", "yunjiuye.yaml"):
        sources = load_sources(SOURCES / filename)
        assert sources and all(s.source_kind == "aggregator" for s in sources)
