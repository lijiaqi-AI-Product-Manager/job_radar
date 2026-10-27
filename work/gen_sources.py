"""把 `count_tenants.py` 的实测结果写成 sources/ 片段（只输出、不落盘到 sources/）。

每条都带实测数字做注释，方便 review 时判断值不值得收。
分数门槛：0 岗的丢掉（宁可少写，不写空源）。

用法：
    python3 work/gen_sources.py --in /tmp/exp/counts.json --out /tmp/exp/patch.yaml
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def line_beisen(c: dict) -> str:
    return (f"  - {{id: beisen-{c['tenant']}, company: {c['company']}, "
            f"params: {{tenant: {c['tenant']}}}}}  # 2026-10-27 官网反查新增：实测 {c['n']} 岗"
            f"{'（JD 全）' if c['jd'] >= c['n'] else ''}")


def line_hotjob(c: dict) -> str:
    host = c.get("host") or ""
    params = f"tenant: {c['tenant']}"
    if host and not host.startswith(c["tenant"]):
        params += f", host: {host}"
    return (f"  - {{id: hotjob-{c['tenant'].lower()}, company: {c['company']}, "
            f"params: {{{params}}}}}  # 2026-10-27 官网反查新增：实测 {c['n']} 岗")


def line_legacy(c: dict, portal: str, variant: str = "") -> str:
    extra = f", variant: {variant}" if variant else ""
    return (f"  - {{id: beisen-legacy-{c['tenant']}, company: {c['company']}, "
            f"params: {{tenant: {c['tenant']}, portal: {portal}{extra}}}}}"
            f"  # 2026-10-27 官网反查新增：实测 {c['n']} 岗")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    a = ap.parse_args()
    rows = json.loads(Path(a.src).read_text(encoding="utf-8"))
    blocks: dict[str, list[str]] = {"beisen": [], "hotjob": [], "feishu": []}
    for c in rows:
        if not c["n"]:
            continue
        ats = c["ats"]
        if ats == "beisen":
            blocks["beisen"].append(line_beisen(c))
        elif ats == "hotjob":
            blocks["hotjob"].append(line_hotjob(c))
        elif ats == "feishu_atsx":
            blocks["feishu"].append(
                f"# {c['company']}: {c['tenant']}.jobs.feishu.cn  实测 {c['n']} 岗")
        elif ats == "beisen_legacy":
            blocks["beisen"].append(line_legacy(c, c.get("portal", "social"),
                                                c.get("variant", "")))
    out = []
    for k, v in blocks.items():
        if v:
            out.append(f"# ==== {k} ({len(v)})")
            out.extend(v)
            out.append("")
    Path(a.out).write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
