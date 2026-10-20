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
    adapters = load_all()
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
