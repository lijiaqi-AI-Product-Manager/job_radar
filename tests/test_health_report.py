import importlib.util
from pathlib import Path

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
