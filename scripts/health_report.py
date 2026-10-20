"""把一次 crawl 的 summary.json 变成健康报告（Markdown）。有问题时退出码为 1，供工作流决定开/关 issue。

用法：python scripts/health_report.py summary.json > report.md
"""

import json
import sys
from pathlib import Path


def render(summary: dict) -> tuple[str, bool]:
    bad = {k: v for k, v in summary.items() if v["status"] != "ok"}
    lines = [f"共 {len(summary)} 个数据源，正常 {len(summary) - len(bad)}，异常 {len(bad)}。", ""]
    if bad:
        lines += ["| 数据源 | 状态 | 原因 |", "|---|---|---|"]
        for sid, v in sorted(bad.items()):
            reason = (v.get("reason") or "").replace("|", "\\|").replace("\n", " ")[:200]
            lines.append(f"| `{sid}` | {v['status']} | {reason} |")
        lines += ["", "- `failed`：抓取出错（站点改版、超时等），岗位状态未改动。",
                  "- `rejected`：结果异常（为空或骤降），已拒收，岗位状态未改动。",
                  "", "处理：先用 `recon-probe` 复现；站点长期不可用或不再允许访问时，在 sources 中设 `enabled: false`。"]
    opened = sum(v.get("opened", 0) for v in summary.values())
    closed = sum(v.get("closed", 0) for v in summary.values())
    lines += ["", f"本次新增 {opened}、下架 {closed}。"]
    return "\n".join(lines), bool(bad)


def main(path: str) -> int:
    report, has_problems = render(json.loads(Path(path).read_text(encoding="utf-8")))
    print(report)
    return 1 if has_problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
