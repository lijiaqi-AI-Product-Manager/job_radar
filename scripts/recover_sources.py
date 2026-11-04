"""限时补采预算未完成与明确瞬时故障；保留完整来源集合和首次采集摘要。"""

import argparse
import copy
import json
import re
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from jobradar.adapters.base import make_client
from jobradar.compliance import RobotsPolicy
from jobradar.pipeline.crawl import crawl
from jobradar.pipeline.ingest import RunResult
from jobradar.sources import load_sources
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts

EVENTS = ("opened", "closed", "changed", "reopened")
TRANSIENT = re.compile(r"^(?:ConnectTimeout|ReadTimeout|WriteTimeout|PoolTimeout|ConnectError|ReadError|WriteError|RemoteProtocolError):|^HTTPStatusError: HTTP (?:429|5\d\d)\b")


def retryable(result):
    return result.get("status") == "failed" and (
        result.get("reason") == "crawl budget exceeded" or bool(TRANSIENT.search(result.get("reason") or "")))


def _latest(jobs):
    return {r["source_id"]: dict(r) for r in jobs.execute(
        "SELECT * FROM source_run WHERE id IN (SELECT MAX(id) FROM source_run GROUP BY source_id)")}


def baseline_from_db(sources, jobs):
    latest = _latest(jobs)
    return {s.id: {**asdict(_result_from_row(latest.get(s.id))),
                   "observed_at": latest.get(s.id, {}).get("ts")} for s in sources if s.enabled}


def _result_from_row(row):
    return RunResult(row["status"], reason=row["error"]) if row else RunResult("failed", reason="no observation")


def _validate(sources, summary):
    expected = {s.id for s in sources if s.enabled}
    if not isinstance(summary, dict) or not expected or set(summary) != expected:
        raise ValueError("crawl summary source set does not match enabled sources")
    for item in summary.values():
        if not isinstance(item, dict) or item.get("status") not in {"ok", "failed", "rejected"}:
            raise ValueError("invalid source result")
        if item.get("reason") is not None and not isinstance(item["reason"], str):
            raise ValueError("invalid source reason")
        if any(type(item.get(k, 0)) is not int or item.get(k, 0) < 0 for k in EVENTS):
            raise ValueError("invalid source event count")


def recover(sources, summary, jobs, texts, *, budget_seconds=1800, source_budget=3600,
            crawl_fn=crawl, clock=time.monotonic):
    _validate(sources, summary)
    if not 0 < budget_seconds <= 3600 or not 0 < source_budget <= 14400:
        raise ValueError("recovery budget must be within 1..3600; source budget within 1..14400 seconds")
    merged = copy.deepcopy(summary)
    latest = _latest(jobs)
    remaining_source = {s.id: source_budget - (latest.get(s.id, {}).get("duration_s") or 0)
                        for s in sources if s.enabled}
    spent = [s.id for s in sources if s.enabled and retryable(summary[s.id]) and remaining_source[s.id] <= 0]
    selected = [s for s in sources if s.enabled and retryable(summary[s.id]) and s.id not in spent]
    # 先补历史上可快速完整读取的来源，长详情源不能再次耗掉整个补采窗口。
    estimates = {r["source_id"]: r["duration_s"] for r in jobs.execute(
        "SELECT source_id,duration_s FROM source_run WHERE id IN "
        "(SELECT MAX(id) FROM source_run WHERE status='ok' GROUP BY source_id)")}
    selected.sort(key=lambda s: (estimates.get(s.id) or 60, latest.get(s.id, {}).get("ts", ""), s.id))
    report = {"schema_version": 1, "scope": "full", "started_at": now_ts(),
              "expected_source_ids": sorted(merged), "before_bad": sum(r["status"] != "ok" for r in merged.values()),
              "attempted": [], "recovered": [], "budget_spent": sorted(spent),
              "eligible": [s.id for s in selected], "budget_seconds": budget_seconds}
    deadline = clock() + budget_seconds
    policy = RobotsPolicy()
    for offset in range(0, len(selected), 24):
        remaining = deadline - clock()
        if remaining <= 0:
            break
        batch = selected[offset:offset + 24]
        ts = now_ts()
        print(f"recovery batch: {len(batch)} sources, {remaining:.0f}s remaining", flush=True)
        outcome = crawl_fn(batch, jobs, texts, ts=ts, max_workers=24,
                           budget_seconds=remaining, source_budget=min(remaining_source[s.id] for s in batch),
                           client_factory=lambda: make_client(policy=policy))
        values = {sid: asdict(value) for sid, value in outcome.items()}
        _validate(batch, values)
        for sid, value in values.items():
            value.update({field: merged[sid].get(field, 0) + value[field] for field in EVENTS})
            value["observed_at"] = ts
            merged[sid] = value
            report["attempted"].append(sid)
            if value["status"] == "ok":
                report["recovered"].append(sid)
        print(f"recovery accepted: {len(report['recovered'])}/{len(report['attempted'])}", flush=True)
    report["after_bad"] = sum(r["status"] != "ok" for r in merged.values())
    report["completed_at"] = now_ts()
    return merged, report


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=Path("sources"))
    parser.add_argument("--summary", type=Path, default=Path("crawl-summary.json"))
    parser.add_argument("--budget-seconds", type=float, default=1800)
    parser.add_argument("--source-budget", type=float, default=3600)
    parser.add_argument("--recovery-only", action="store_true")
    args = parser.parse_args()
    sources = [s for s in load_sources(args.sources) if s.enabled]
    if len({s.id for s in sources}) != len(sources):
        raise ValueError("duplicate source IDs")
    with closing(connect(args.home / "jobs.db", "jobs")) as jobs, \
            closing(connect(args.home / "jd_text.db", "text")) as texts:
        baseline = baseline_from_db(sources, jobs)
        summary = baseline if args.recovery_only else json.loads(args.summary.read_text(encoding="utf-8"))
        _validate(sources, summary)
        for sid, value in summary.items():
            value.setdefault("observed_at", baseline[sid]["observed_at"])
        write_json("initial-summary.json", summary)
        merged, report = recover(sources, summary, jobs, texts, budget_seconds=args.budget_seconds,
                                 source_budget=args.source_budget)
        report["scope"] = "recovery_only" if args.recovery_only else "full"
        write_json("recovery-report.json", report)
        write_json(args.summary, merged)


if __name__ == "__main__":
    main()
