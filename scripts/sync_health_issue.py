"""维护一条持续更新的健康问题；完整恢复才关闭，复发时复用已标记的问题。"""

import argparse
import json
import subprocess
from pathlib import Path

from health_report import MARKER, issue_action


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--bad", type=int, required=True)
    args = parser.parse_args()
    body = args.report.read_text(encoding="utf-8").strip()
    if not body:
        raise ValueError("refusing to replace an issue with an empty report")
    if MARKER not in body:
        args.report.write_text(MARKER + "\n" + body + "\n", encoding="utf-8")
    issues = json.loads(gh("issue", "list", "--label", "data-health", "--state", "all", "--limit", "100",
                           "--json", "number,state,body"))
    for issue in issues:
        issue["state"] = issue["state"].lower()
    action, number = issue_action(issues, bool(args.bad))
    if action in {"update", "reopen", "close"}:
        gh("issue", "edit", str(number), "--body-file", str(args.report))
    if action == "reopen":
        gh("issue", "reopen", str(number))
    elif action == "close":
        gh("issue", "close", str(number), "--reason", "completed")
    elif action == "create":
        gh("label", "create", "data-health", "--color", "B60205", "--description", "数据源健康与恢复状态", "--force")
        gh("issue", "create", "--title", "数据源健康报告", "--label", "data-health", "--body-file", str(args.report))
    print(f"health issue: {action} {number or ''}")


if __name__ == "__main__":
    main()
