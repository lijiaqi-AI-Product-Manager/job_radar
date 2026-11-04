import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "health_report", Path(__file__).parent.parent / "scripts" / "health_report.py")
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


def test_all_ok():
    report, bad = health.render({"a": {"status": "ok", "opened": 3, "closed": 1, "reason": None}})
    assert not bad and "异常 0" in report and "新增 3、下架 1" in report


def test_problems_are_listed():
    report, bad = health.render({
        "a": {"status": "ok", "opened": 0, "closed": 0, "reason": None},
        "b": {"status": "failed", "opened": 0, "closed": 0, "reason": "HTTPStatusError: 500 | x"},
        "c": {"status": "rejected", "opened": 0, "closed": 0, "reason": "job count dropped 100 -> 3"},
    })
    assert bad
    assert "| `b` | failed | HTTPStatusError: 500 \\| x |" in report
    assert "`c`" in report and "异常 2" in report


@pytest.mark.parametrize("content", [None, "", "{", "{}", "[]", '{"s1": {"opened": 0}}',
                                     '{"s1": {"status": "failed", "reason": 123}}'])
def test_unavailable_summary_never_produces_an_empty_or_healthy_report(tmp_path, capsys, content):
    path = tmp_path / "crawl-summary.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert health.main(str(path)) != 0
    output = capsys.readouterr()
    assert output.out.strip()
    assert "无法确认" in output.out
    assert "异常 0" not in output.out
    assert "Traceback" not in output.err


def test_cancelled_run_cannot_close_the_health_issue_even_with_ok_results(tmp_path, capsys):
    path = tmp_path / "crawl-summary.json"
    path.write_text(json.dumps({"s1": {"status": "ok"}}), encoding="utf-8")
    url = "https://github.com/example/repo/actions/runs/123"
    assert health.main(str(path), run_status="cancelled", run_url=url) != 0
    output = capsys.readouterr().out
    assert "cancelled" in output and url in output
    assert "无法确认" in output


def test_budget_exhaustion_is_distinguished_from_site_errors():
    report, bad = health.render({
        "later": {"status": "failed", "reason": "crawl budget exceeded"},
        "broken": {"status": "failed", "reason": "HTTP 500"},
        "protected": {"status": "rejected", "reason": "empty result"},
    })
    assert bad
    assert "预算未完成 1" in report and "采集失败 1" in report and "保护性拒收 1" in report
    assert "<details>" in report and "`later`" in report


def test_cli_produces_a_report_for_the_cancelled_workflow(tmp_path):
    path = tmp_path / "crawl-summary.json"
    path.write_text("", encoding="utf-8")
    url = "https://github.com/example/repo/actions/runs/123"
    result = subprocess.run(
        [sys.executable, str(Path(health.__file__)), str(path), "--run-status", "cancelled",
         "--run-url", url], capture_output=True, text=True, encoding="utf-8",
        env=os.environ | {"PYTHONUTF8": "1"}, check=False,
    )
    assert result.returncode == 1
    assert "无法确认" in result.stdout and url in result.stdout
    assert not result.stderr


def test_partial_summary_cannot_close_full_source_health():
    with pytest.raises(ValueError, match="source set"):
        health.render({"a": {"status": "ok"}}, expected_ids={"a", "b"})


def test_recovery_context_does_not_disguise_old_ok_observations():
    report, bad = health.render({"a": {"status": "ok", "observed_at": "2026-11-01T00:00:00Z"}},
                                expected_ids={"a"}, now="2026-11-04T00:00:00Z")
    assert bad and "观测超过 24 小时" in report


def test_standing_health_issue_reuses_only_marked_closed_reports():
    assert health.issue_action([{"number": 31, "state": "closed", "body": health.MARKER},
                                {"number": 13, "state": "closed", "body": "historical"}], True) == ("reopen", 31)
    assert health.issue_action([{"number": 13, "state": "closed", "body": "historical"}], True) == ("create", None)
    assert health.issue_action([{"number": 31, "state": "open", "body": "existing"}], True) == ("update", 31)
    assert health.issue_action([{"number": 31, "state": "open", "body": health.MARKER}], False) == ("close", 31)


@pytest.mark.parametrize("context", [{"schema_version": 1}, {"schema_version": 1, "expected_source_ids": ["s1"]}])
def test_incomplete_recovery_context_never_suppresses_report(tmp_path, capsys, context):
    summary = tmp_path / "summary.json"
    summary.write_text('{"s1":{"status":"ok"}}', encoding="utf-8")
    metadata = tmp_path / "context.json"
    metadata.write_text(json.dumps(context), encoding="utf-8")
    assert health.main(str(summary), context_path=str(metadata)) == 1
    assert "无法确认" in capsys.readouterr().out


def test_report_separates_scheduling_from_started_recovery(tmp_path, capsys):
    summary = tmp_path / "summary.json"
    summary.write_text('{"a":{"status":"failed"},"b":{"status":"ok"}}', encoding="utf-8")
    metadata = tmp_path / "context.json"
    metadata.write_text(json.dumps({"schema_version": 1, "expected_source_ids": ["a", "b"],
                                    "scheduled": ["a", "b"], "attempted": ["b"], "recovered": ["b"],
                                    "before_bad": 2, "after_bad": 1}), encoding="utf-8")
    assert health.main(str(summary), context_path=str(metadata)) == 1
    report = capsys.readouterr().out
    assert "排队 2 个" in report and "实际启动 1 个" in report and "恢复 1 个" in report
