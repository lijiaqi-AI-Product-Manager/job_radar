import json
from pathlib import Path

from helpers import T, make_job
from jobradar.core import queries as q
from jobradar.models import Compliance, SourceConfig
from jobradar.pipeline.ingest import ingest_run


def test_packaged_source_catalog_matches_reviewed_configuration():
    from jobradar.source_catalog import CATALOG_PATH, build_catalog
    from jobradar.sources import load_sources

    expected = build_catalog(load_sources(Path(__file__).parents[1] / "sources"))
    assert json.loads(CATALOG_PATH.read_text(encoding="utf-8")) == expected


def test_catalog_only_contains_public_classification_and_review_dates():
    from jobradar.source_catalog import build_catalog

    source = SourceConfig(
        id="notice",
        company="示例",
        adapter="jysd",
        source_kind="aggregator",
        params={"session": "never-publish-this-value"},
        compliance=Compliance(checked_on="2026-11-01", robots="allowed", terms="公开页面"),
    )
    info = build_catalog([source])["notice"]
    assert info["source_kind"] == "aggregator"
    assert info["record_kind"] == "recruitment_notice"
    assert info["compliance_checked_on"] == "2026-11-01"
    assert "never-publish-this-value" not in json.dumps(info)


def test_search_and_detail_report_source_classification_without_prefix_guessing(
    jobs_db, monkeypatch
):
    from jobradar import source_catalog

    catalog = {
        "s1": {
            "source_kind": "aggregator",
            "record_kind": "recruitment_notice",
            "adapter": "jysd",
            "compliance_checked_on": "2026-11-01",
            "enabled": True,
        }
    }
    monkeypatch.setattr(source_catalog, "catalog", lambda: catalog)
    ingest_run(jobs_db, "s1", [make_job(1)], ts=T(1))
    ingest_run(jobs_db, "jysd-unknown", [make_job(1, source_id="jysd-unknown")], ts=T(1))
    rows = {r["id"]: r for r in q.search_jobs(jobs_db)}
    assert rows["s1:1"]["source_kind"] == "aggregator"
    assert rows["s1:1"]["record_kind"] == "recruitment_notice"
    assert rows["jysd-unknown:1"]["source_kind"] == "unknown"
    assert rows["jysd-unknown:1"]["record_kind"] == "unknown"
    detail = q.get_job(jobs_db, None, "s1:1")
    assert detail["source"]["compliance_checked_on"] == "2026-11-01"
    assert detail["source"]["record_kind"] == "recruitment_notice"
    counts=q.data_summary(jobs_db)
    assert counts['by_record_kind']=={'recruitment_notice':1,'unknown':1}
    assert counts['by_source_kind']=={'aggregator':1,'unknown':1}
