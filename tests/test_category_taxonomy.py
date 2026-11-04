"""固定职类词表不能被某条平台原值覆盖，安装包与源码使用同一词表。"""

import shutil
from pathlib import Path

import pytest
import yaml

from helpers import T, make_job
from jobradar import normalize
from jobradar.core import queries as q
from jobradar.pipeline.ingest import ingest_run


def test_raw_finance_label_cannot_shadow_the_supported_alias(jobs_db):
    rows = [make_job(1, title="会计专员", category="职能", subcategory="财务审计", cities=["苏州"]),
            make_job(2, title="财务经理", category="财务", subcategory=None, cities=["北京"]),
            make_job(3, title="行政专员", category="职能", subcategory="行政", cities=["苏州"])]
    ingest_run(jobs_db, "s1", rows, ts=T(1))
    meta = {}
    found = q.search_jobs(jobs_db, category="财务", cities=["苏州", "无锡"], exclude_cities=["上海"], meta=meta)
    assert [r["id"] for r in found] == ["s1:1"]
    assert meta["category_match"]["match"] == "alias"
    assert "财务审计" in meta["category_match"]["matched"]
    assert q.search_jobs(jobs_db, category="财务", meta=meta)
    assert {r["id"] for r in q.search_jobs(jobs_db, category="会计")} == {"s1:1", "s1:2"}


def test_vocabulary_is_fixed_even_for_empty_or_polluted_snapshots(jobs_db):
    doc = yaml.safe_load((Path(__file__).parents[1] / "taxonomy/categories.yaml").read_text(encoding="utf-8"))
    expected = sorted({r[k] for r in doc["rules"] for k in ("category", "subcategory")})
    assert q.category_vocabulary(jobs_db) == expected
    ingest_run(jobs_db, "s1", [make_job(1, category="互联网 / 电子 / 网游", subcategory="财务")], ts=T(1))
    assert q.category_vocabulary(jobs_db) == expected
    meta = {}
    assert q.search_jobs(jobs_db, category="互联网 / 电子 / 网游", meta=meta) == []
    assert meta["category_match"]["match"] == "none"


@pytest.mark.parametrize("term", ["backend", "Backend", "ＢＡＣＫＥＮＤ", "后端"])
def test_equivalent_role_names_include_canonical_and_legacy_values(jobs_db, term):
    ingest_run(jobs_db, "s1", [make_job(1, category="技术", subcategory="后端"),
                              make_job(2, category="Backend", subcategory=None),
                              make_job(3, category="技术", subcategory="算法")], ts=T(1))
    assert {r["id"] for r in q.search_jobs(jobs_db, category=term)} == {"s1:1", "s1:2"}


@pytest.mark.parametrize("category", ["", " ", [], 123])
def test_invalid_category_does_not_silently_broaden_search(jobs_db, category):
    with pytest.raises(ValueError, match="职类"):
        q.search_jobs(jobs_db, category=category)


def test_title_categorization_works_from_packaged_taxonomy(tmp_path, monkeypatch):
    packaged = tmp_path / "installed" / "_data"
    packaged.mkdir(parents=True)
    shutil.copyfile(normalize.TAXONOMY, packaged / "categories.yaml")
    monkeypatch.setattr(normalize, "TAXONOMY", tmp_path / "missing.yaml")
    monkeypatch.setattr(normalize, "files", lambda _: packaged.parent, raising=False)
    normalize._rules.cache_clear()
    try:
        assert normalize.categorize("财务会计") == ("职能", "财务审计")
    finally:
        normalize._rules.cache_clear()
