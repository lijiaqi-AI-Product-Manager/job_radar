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
