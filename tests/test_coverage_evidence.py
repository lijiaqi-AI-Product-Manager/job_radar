import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coverage_report", ROOT / "scripts/coverage_report.py")
cov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cov)


def _export(source, output):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/export_coverage_evidence.py"),
         "--input", str(source), "--output", str(output)],
        capture_output=True, text=True, encoding="utf-8",
    )


def test_export_preserves_first_entry_and_original_timestamp(tmp_path):
    source, output = tmp_path / "careers.jsonl", tmp_path / "evidence.yaml"
    rows = [
        {"company": "乙公司", "best": {"url": "https://b.example/jobs", "snippet": "discard"},
         "at": "2026-10-25T16:28:54Z", "all": [{"url": "https://other.example/"}]},
        {"company": "甲公司", "best": {"url": "https://a.example/jobs"}},
        {"company": "乙公司", "best": {"url": "https://replacement.example/"},
         "at": "2026-10-30T00:00:00Z"},
        {"company": "无入口公司", "best": {}},
    ]
    source.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    result = _export(source, output)
    assert result.returncode == 0, result.stderr
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert payload == {"schema_version": 1, "entries": [
        {"company": "乙公司", "url": "https://b.example/jobs", "checked_at": "2026-10-25T16:28:54Z"},
        {"company": "甲公司", "url": "https://a.example/jobs", "checked_at": None},
    ]}
    assert cov.load_careers(output) == {
        "乙公司": "https://b.example/jobs", "甲公司": "https://a.example/jobs",
    }
    first_export = output.read_bytes()
    assert _export(source, output).returncode == 0
    assert output.read_bytes() == first_export


@pytest.mark.parametrize("contents", [
    '{"company": "甲公司", "best": {"url": "https://a.example/"}}\ninvalid json',
    '{"company": "无入口", "best": {}}',
    '{"company": "甲公司", "best": {"url": "file:///private"}}',
    '{"company": "甲公司", "best": {"url": "https://a.example/"}, "at": "yesterday"}',
])
def test_invalid_export_does_not_replace_existing_evidence(tmp_path, contents):
    source, output = tmp_path / "careers.jsonl", tmp_path / "evidence.yaml"
    source.write_text(contents, encoding="utf-8")
    output.write_text("keep existing evidence", encoding="utf-8")
    result = _export(source, output)
    assert result.returncode != 0
    assert output.read_text(encoding="utf-8") == "keep existing evidence"


def test_missing_export_input_does_not_create_output(tmp_path):
    output = tmp_path / "evidence.yaml"
    assert _export(tmp_path / "missing.jsonl", output).returncode != 0
    assert not output.exists()


def test_missing_evidence_is_an_error_instead_of_all_unknown(tmp_path):
    with pytest.raises(FileNotFoundError):
        cov.load_careers(tmp_path / "missing.yaml")


@pytest.mark.parametrize("payload", [
    {"schema_version": 2, "entries": []},
    {"schema_version": 1},
    {"schema_version": 1, "entries": [{"company": "甲公司", "url": ""}]},
    {"schema_version": 1, "entries": [{"company": "甲公司", "url": "file:///private"}]},
    {"schema_version": 1, "entries": [{"company": "甲公司", "url": "https://a.example/", "checked_at": "yesterday"}]},
    {"schema_version": 1, "entries": [
        {"company": "甲公司", "url": "https://a.example/"},
        {"company": "甲公司", "url": "https://b.example/"},
    ]},
])
def test_invalid_snapshot_is_not_silently_accepted(tmp_path, payload):
    path = tmp_path / "evidence.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError):
        cov.load_careers(path)


def test_clean_checkout_reproduces_attribution_and_ignores_work_files(tmp_path):
    targets = cov.load_targets()
    companies = {s.company for s in cov.load_sources(ROOT / "sources") if s.enabled}
    matched = cov.match(targets, companies)
    expected = cov.uncovered_reasons(targets, matched, cov.load_careers())
    assert sum(n for reason, n in expected.items() if reason != "unknown") > 0

    checkout = tmp_path / "checkout"
    for directory in ("src", "sources", "targets", "scripts"):
        shutil.copytree(ROOT / directory, checkout / directory, ignore=shutil.ignore_patterns("__pycache__"))

    def report():
        result = subprocess.run(
            [sys.executable, str(checkout / "scripts/coverage_report.py"), "--json"],
            cwd=checkout, capture_output=True, text=True, encoding="utf-8", check=True,
        )
        return json.loads(result.stdout)

    clean_report = report()
    assert clean_report["uncovered_reasons"] == expected
    assert clean_report["covered"] == sum(bool(v) and k not in (targets.get("blocked") or {})
                                          for k, v in matched.items())
    assert sum(expected.values()) + clean_report["covered"] + clean_report["blocked"] == len(matched)
    (checkout / "work").mkdir()
    target = next(name for name, found in matched.items()
                  if not found and name not in (targets.get("blocked") or {}))
    (checkout / "work/careers_confirmed.jsonl").write_text(json.dumps({
        "company": target, "best": {"url": "https://changed.zhiye.com/"},
    }, ensure_ascii=False), encoding="utf-8")
    assert report() == clean_report
