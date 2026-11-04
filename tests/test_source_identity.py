"""同租户只采集一次，历史分发不因配置停用而被改写。"""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from helpers import T, make_job
from jobradar import cli, source_catalog
from jobradar.core import queries as q
from jobradar.models import Compliance, SourceConfig
from jobradar.pipeline.ingest import ingest_run


def source(sid, adapter="hotjob", **params):
    return SourceConfig(id=sid, company=sid, adapter=adapter, params=params,
                        compliance=Compliance(checked_on="2026-11-04", robots="allowed", terms="离线样本"))


def test_tenant_identity_uses_platform_scope_and_allows_disjoint_projects():
    a = source("a", tenant="SU123", host="brand.hotjob.cn")
    b = source("b", tenant="su123", host="wecruit.hotjob.cn")
    assert source_catalog.duplicate_enabled_tenants([a, b]) == [["a", "b"]]
    b.recruit_types = ["social"]
    assert source_catalog.duplicate_enabled_tenants([a, b]) == []
    a = source("a", "beisen", tenant="brand", host="Jobs.Example.test.")
    b = source("b", "beisen", tenant="alias", host="jobs.example.test")
    assert source_catalog.duplicate_enabled_tenants([a, b]) == [["a", "b"]]
    b.params["host"] = "other.example.test"
    assert source_catalog.duplicate_enabled_tenants([a, b]) == []


def test_enabled_repository_sources_do_not_repeat_a_platform_tenant():
    from jobradar.sources import load_sources

    sources = load_sources(Path(__file__).parents[1] / "sources")
    assert source_catalog.duplicate_enabled_tenants(sources) == []


def test_catalog_keeps_disabled_tenant_peer_without_publishing_request_parameters():
    a = source("a", tenant="SU123", transient_session="never-publish")
    b = source("b", tenant="su123")
    b.enabled = False
    result = source_catalog.build_catalog([a, b])
    assert result["a"]["tenant_peers"] == ["b"]
    assert result["b"]["tenant_peers"] == ["a"]
    assert result["b"]["enabled"] is False
    assert "never-publish" not in json.dumps(result)


@pytest.mark.parametrize("entry", ["search", "detail"])
def test_disabled_and_shared_tenant_records_remain_visible_with_human_readable_warnings(jobs_db, monkeypatch, entry):
    monkeypatch.setattr(source_catalog, "catalog", lambda: {
        "a": {"adapter":"hotjob", "enabled":True, "tenant_peers":["b"]},
        "b": {"adapter":"hotjob", "enabled":False, "tenant_peers":["a"]},
    })
    ingest_run(jobs_db, "b", [make_job(1, source_id="b")], ts=T(1))
    before = [tuple(r) for r in jobs_db.execute("SELECT * FROM job")]
    events = [tuple(r) for r in jobs_db.execute("SELECT * FROM job_event")]
    row = q.search_jobs(jobs_db)[0] if entry == "search" else q.get_job(jobs_db, None, "b:1")
    assert row["availability"] == "unconfirmed_disabled"
    assert "暂停" in row["availability_label"] and row["source_tenant_peers"] == ["a"]
    assert any("历史" in warning for warning in row["source_warnings"])
    assert any("重复" in warning for warning in row["source_warnings"])
    assert [tuple(r) for r in jobs_db.execute("SELECT * FROM job")] == before
    assert [tuple(r) for r in jobs_db.execute("SELECT * FROM job_event")] == events


def test_record_overlap_is_a_readonly_candidate_not_a_tenant_or_employer_decision(jobs_db):
    meta = {sid:{"adapter":adapter} for sid,adapter in (("a","beisen"),("b","beisen"),("c","hotjob"))}
    for sid in meta:
        ingest_run(jobs_db, sid, [make_job(i, source_id=sid, company=sid, cities=["苏州", "无锡"])
                                 for i in range(1, 4)], ts=T(1))
    # 同标题或相同编号不足以合并不同城市、类型或平台。
    ingest_run(jobs_db, "b", [make_job(i, source_id="b", company="b", cities=["无锡", "苏州"])
                             for i in range(1, 4)] + [make_job(4, source_id="b", company="b")], ts=T(2))
    before = jobs_db.total_changes
    result = q.source_record_overlaps(jobs_db, meta, minimum_overlap=3, minimum_ratio=.9)
    assert jobs_db.total_changes == before
    assert result["collision_groups"] == 3
    assert len(result["pairs"]) == 1
    pair = result["pairs"][0]
    assert (pair["source_a"],pair["source_b"],pair["overlap"],pair["records_a"],pair["records_b"]) == ("a","b",3,3,4)
    assert pair["same_configured_tenant"] is False
    assert pair["classification"] == "record_overlap_candidate"
    assert pair["ratio_a"] == 1 and pair["ratio_b"] == .75
    assert len(pair["sample_job_ids"]) <= 3
    assert "canonical_company" not in pair


@pytest.mark.parametrize("options", [{"minimum_overlap":0}, {"minimum_overlap":True},
    {"minimum_ratio":0}, {"minimum_ratio":1.1}, {"minimum_ratio":float("nan")}])
def test_invalid_overlap_thresholds_are_rejected(jobs_db, options):
    with pytest.raises(ValueError):
        q.source_record_overlaps(jobs_db, {}, **options)


def test_shared_tenant_warning_is_visible_in_human_table(capsys):
    from argparse import Namespace

    cli._emit(Namespace(table=True), {"results":[{"title":"研发工程师", "company":"示例",
        "source_tenant_peers":["other"], "availability_label":"历史记录，来源已暂停采集"}]})
    output = capsys.readouterr().out
    assert "同一招聘租户" in output and "重复" in output and "历史记录，来源已暂停采集" in output


def test_overlap_does_not_merge_different_cities_or_qualifications(jobs_db):
    catalog = {sid:{"adapter":"hotjob"} for sid in ("a","b")}
    ingest_run(jobs_db, "a", [make_job(1, source_id="a", cities=["上海"]),
                              make_job(2, source_id="a", degree_min="本科")], ts=T(1))
    ingest_run(jobs_db, "b", [make_job(1, source_id="b", cities=["苏州"]),
                              make_job(2, source_id="b", degree_min="硕士")], ts=T(1))
    assert q.source_record_overlaps(jobs_db, catalog, minimum_overlap=1)["collision_groups"] == 0


def test_report_command_does_not_write_databases_and_csv_does_not_evaluate_cells(tmp_path, jobs_db, capsys):
    import yaml

    script = Path(__file__).parents[1] / "scripts/find_duplicate_tenants.py"
    spec = importlib.util.spec_from_file_location("find_duplicate_tenants", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sources = [source("a", tenant="su1"), source("b", tenant="su2")]
    for sid in ("a", "b"):
        ingest_run(jobs_db, sid, [make_job(1, source_id=sid, company=sid)], ts=T(1))
    db_path = tmp_path / "jobs.db"
    with sqlite3.connect(db_path) as output:
        jobs_db.backup(output)
    before = db_path.read_bytes()
    configs = tmp_path / "sources.yaml"
    configs.write_text(yaml.safe_dump({"sources":[s.model_dump(mode="json") for s in sources]}), encoding="utf-8")
    csv_path = tmp_path / "overlaps.csv"
    assert module.main(["--db",str(db_path),"--sources",str(configs),"--csv",str(csv_path),
                        "--minimum-overlap","1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["pairs"]) == 1 and db_path.read_bytes() == before
    pair = result["pairs"][0]
    pair["source_a"] = "=HYPERLINK(unsafe)"
    module.write_csv(csv_path, [pair])
    assert "'=HYPERLINK(unsafe)" in csv_path.read_text(encoding="utf-8-sig")
