"""把一次 crawl 的 summary.json 变成健康报告（Markdown）。有问题时退出码为 1，供工作流决定开/关 issue。

用法：python scripts/health_report.py summary.json > report.md
"""

import argparse
import json
import sys
from pathlib import Path


def render(summary: dict) -> tuple[str, bool]:
    if not isinstance(summary, dict) or not summary:
        raise ValueError("empty or invalid crawl summary")
    for result in summary.values():
        if not isinstance(result, dict) or result.get("status") not in {"ok", "failed", "rejected"}:
            raise ValueError("invalid source result")
        if result.get("reason") is not None and not isinstance(result["reason"], str):
            raise ValueError("invalid source reason")
        for field in ("opened", "closed"):
            value = result.get(field, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("invalid source count")
    bad = {k: v for k, v in summary.items() if v["status"] != "ok"}
    lines = [f"共 {len(summary)} 个数据源，正常 {len(summary) - len(bad)}，异常 {len(bad)}。", ""]
    if bad:
        deferred = sum(v.get("reason") == "crawl budget exceeded" for v in bad.values())
        rejected = sum(v["status"] == "rejected" for v in bad.values())
        failed = len(bad) - deferred - rejected
        lines += [f"其中：采集失败 {failed}、保护性拒收 {rejected}、预算未完成 {deferred}。",
                  "预算未完成包括尚未启动或中途停止，不能认定站点失效；下次仍需继续采集。", ""]
        active = {sid: v for sid, v in bad.items() if v.get("reason") != "crawl budget exceeded"}
        if active:
            lines += ["| 数据源 | 状态 | 原因 |", "|---|---|---|"]
        for sid, v in sorted(active.items()):
            reason = (v.get("reason") or "").replace("|", "\\|").replace("\n", " ")[:200]
            lines.append(f"| `{sid}` | {v['status']} | {reason} |")
        if deferred:
            lines += ["", f"<details><summary>预算未完成：{deferred} 个数据源</summary>", ""]
            lines += [f"- `{sid}`" for sid, v in sorted(bad.items())
                      if v.get("reason") == "crawl budget exceeded"]
            lines += ["", "</details>"]
        lines += ["", "- `failed`：抓取出错（站点改版、超时等），岗位状态未改动。",
                  "- `rejected`：结果异常（为空或骤降），已拒收，岗位状态未改动。",
                  "", "处理：先用 `recon-probe` 复现；站点长期不可用或不再允许访问时，在 sources 中设 `enabled: false`。"]
    opened = sum(v.get("opened", 0) for v in summary.values())
    closed = sum(v.get("closed", 0) for v in summary.values())
    lines += ["", f"本次新增 {opened}、下架 {closed}。"]
    return "\n".join(lines), bool(bad)


def main(path: str, *, run_status: str = "success", run_url: str | None = None) -> int:
    lines = ["# 数据源健康报告", ""]
    if run_url:
        lines += [f"[本次采集运行]({run_url})", ""]
    incomplete = run_status != "success"
    if incomplete:
        lines += [f"本轮流水线状态：`{run_status}`，无法确认采集完整完成。", ""]
    try:
        report, has_problems = render(json.loads(Path(path).read_text(encoding="utf-8")))
        lines.append(report)
    except (OSError, ValueError, TypeError) as error:
        lines += ["采集摘要缺失、为空或格式不完整，无法确认数据源已恢复。",
                  f"诊断类型：`{type(error).__name__}`。请查看本次运行的采集步骤。",
                  "未完成采集不能作为关岗、清空历史或关闭健康问题的依据。"]
        has_problems = True
    print("\n".join(lines))
    return 1 if has_problems or incomplete else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--run-status", default="success")
    parser.add_argument("--run-url")
    args = parser.parse_args()
    sys.exit(main(args.path, run_status=args.run_status, run_url=args.run_url))
