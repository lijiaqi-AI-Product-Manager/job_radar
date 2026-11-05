import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from helpers import T, make_job
from jobradar.adapters.base import load_all
from jobradar.models import Compliance, SourceConfig
from jobradar.pipeline.detail_checkpoint import DetailCheckpoint

ROOT = Path(__file__).resolve().parents[1]


def transfer_module():
    spec = importlib.util.spec_from_file_location("detail_progress", ROOT / "scripts/detail_progress.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source():
    return SourceConfig(id="s1", company="腾讯", adapter="hotjob",
                        params={"detail_cache_hours": 168},
                        compliance=Compliance(checked_on="2026-11-04", robots="allowed", terms="公开岗位"))


def exported(tmp_path):
    mod = transfer_module()
    config = source()
    adapter = load_all()["hotjob"]
    original = tmp_path / "original"
    DetailCheckpoint(original, config, adapter, T(1)).record(make_job(1, description="已读取职责"))
    payload = mod.export_progress(original, [config], ["s1"], now=T(2))
    return mod, config, adapter, payload


def test_transfer_keeps_actual_detail_time_and_newer_destination(tmp_path):
    mod, config, adapter, payload = exported(tmp_path)
    destination = tmp_path / "destination"
    report = mod.import_progress(destination, payload, [config], ["s1"], now=T(2))
    assert report["available_details"] == 1
    first = DetailCheckpoint(destination, config, adapter, T(2)).load()["1"]
    assert (first["description"], first["fetched_at"]) == ("已读取职责", T(1))
    DetailCheckpoint(destination, config, adapter, T(3)).record(make_job(1, description="更近正文"))
    report = mod.import_progress(destination, payload, [config], ["s1"], now=T(4))
    assert report["preserved_newer"] == 1
    assert DetailCheckpoint(destination, config, adapter, T(4)).load()["1"]["description"] == "更近正文"


@pytest.mark.parametrize("mutation", ["signature", "employer", "future", "unknown-field", "duplicate"])
def test_invalid_transfer_does_not_write_any_destination_records(tmp_path, mutation):
    mod, config, adapter, payload = exported(tmp_path)
    entry = payload["sources"][0]["entries"][0]
    if mutation == "signature":
        entry["signature"] = "0" * 64
    elif mutation == "employer":
        entry["job"]["company"] = "兄弟公司"
    elif mutation == "future":
        entry["observed_at"] = T(10)
    elif mutation == "unknown-field":
        entry["job"]["session_value"] = "should-not-exist"
    else:
        payload["sources"][0]["entries"].append(dict(entry))
    destination = tmp_path / "destination"
    with pytest.raises(ValueError):
        mod.import_progress(destination, payload, [config], ["s1"], now=T(2))
    assert not list(destination.rglob("*.json"))


def test_transfer_requires_explicit_enabled_source_selection_and_fresh_progress(tmp_path):
    mod, config, _, payload = exported(tmp_path)
    for selected, configs, now in [([], [config], T(2)), (["../s1"], [config], T(2)),
                                    (["s1"], [config.model_copy(update={"enabled": False})], T(2)),
                                    (["s1"], [config], T(20))]:
        with pytest.raises(ValueError):
            mod.import_progress(tmp_path / "destination", payload, configs, selected, now=now)


def test_transfer_file_digest_and_expanded_size_are_checked_before_writing(tmp_path, monkeypatch):
    mod, config, _, payload = exported(tmp_path)
    path = tmp_path / "progress.json.gz"
    sha = mod.write_payload(path, payload)
    assert mod.read_payload(path, sha) == payload
    with pytest.raises(ValueError):
        mod.read_payload(path, "0" * 64)
    bomb = tmp_path / "expanded.json.gz"
    compressed = gzip.compress(b" " * 128000)
    bomb.write_bytes(compressed)
    assert len(compressed) < 1024
    monkeypatch.setattr(mod, "MAX_BYTES", 1024)
    with pytest.raises(ValueError):
        mod.read_payload(bomb, hashlib.sha256(compressed).hexdigest())
    assert not (tmp_path / "destination").exists()


def test_transfer_contains_no_source_parameters_and_export_does_not_overwrite(tmp_path):
    mod, config, _, payload = exported(tmp_path)
    assert "detail_cache_hours" not in json.dumps(payload)
    path = tmp_path / "progress.json.gz"
    mod.write_payload(path, payload)
    with pytest.raises(FileExistsError):
        mod.write_payload(path, payload)


def test_entire_transfer_is_validated_before_valid_source_is_written(tmp_path):
    mod, config, _, payload = exported(tmp_path)
    second = json.loads(json.dumps(payload["sources"][0]))
    second["source_id"] = "s2"
    second["entries"][0]["job"]["source_id"] = "s2"
    second["entries"][0]["signature"] = "0" * 64
    payload["sources"].append(second)
    configs = [config, config.model_copy(update={"id": "s2"})]
    destination = tmp_path / "destination"
    with pytest.raises(ValueError):
        mod.import_progress(destination, payload, configs, ["s1", "s2"], now=T(2))
    assert not list(destination.rglob("*.json"))
