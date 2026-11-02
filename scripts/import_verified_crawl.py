"""在工作副本恢复完整公开观测；保留实际时间，继续经过标准入库保护。"""

import argparse
import gzip
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from jobradar import __version__
from jobradar.models import Job
from jobradar.pipeline.crawl import _expected_max
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.sources import load_sources
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts, parse_ts


def config_sha256(source):
    value = json.dumps(source.model_dump(mode="json"), ensure_ascii=False,
                       sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def _validated(payload, sources, now, known_hosts=None):
    if payload.get("schema_version") != 1 or payload.get("application_version") != __version__:
        raise ValueError("unsupported observation schema or application version")
    clock = parse_ts(now)
    captured = parse_ts(payload["captured_at"])
    if not clock - timedelta(hours=24) <= captured <= clock + timedelta(minutes=2):
        raise ValueError("capture timestamp outside recovery window")
    configs = {s.id: s for s in sources if s.enabled}
    records = payload.get("sources")
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError("invalid source count")
    checked, seen = [], set()
    for record in records:
        sid = record["source_id"]
        source = configs.get(sid)
        if sid in seen or source is None:
            raise ValueError("duplicate, unknown or disabled source")
        seen.add(sid)
        if record.get("complete") is not True or record.get("source_config_sha256") != config_sha256(source):
            raise ValueError("incomplete observation or changed source configuration")
        observed, completed = parse_ts(record["observed_at"]), parse_ts(record["completed_at"])
        if not clock - timedelta(hours=24) <= observed <= completed <= captured:
            raise ValueError("invalid observation time sequence")
        host = source.params.get("host")
        if not host and source.adapter == "beisen":
            host = f"{source.params['tenant']}.zhiye.com"
        if not host and source.adapter == "hotjob":
            host = "wecruit.hotjob.cn"
        allowed_hosts = {host} if host else set()
        if source.adapter not in {"beisen", "hotjob", "jysd"}:
            allowed_hosts.update((known_hosts or {}).get(sid, set()))
        if not allowed_hosts:
            raise ValueError("adapter requires an explicitly verified recovery host")
        values = record.get("jobs")
        if not isinstance(values, list) or not 1 <= len(values) <= 50000:
            raise ValueError("empty or oversized observation")
        jobs, job_ids = [], set()
        for value in values:
            job = Job.model_validate(value, strict=True)
            url = urlsplit(job.url)
            if (job.source_id != sid or not job.source_job_id.strip() or job.company != source.company
                    or job.recruit_type not in source.recruit_types or job.id in job_ids
                    or url.scheme != "https" or url.hostname not in allowed_hosts or url.username or url.password
                    or url.port not in (None, 443)):
                raise ValueError("job identity, employer, type or public host mismatch")
            if job.text_observed_at and parse_ts(job.text_observed_at) > observed:
                raise ValueError("text observation is newer than the source observation")
            for day in (job.apply_end, job.publish_at):
                if day is not None:
                    if len(day) != 10 or not 1900 <= date.fromisoformat(day).year < 2100:
                        raise ValueError("invalid explicit date")
            jobs.append(job)
            job_ids.add(job.id)
        checked.append((source, record["observed_at"], jobs,
                        (completed - observed).total_seconds()))
    return checked


def apply_observations(jobs, texts, payload, sources, *, now):
    known_hosts = {}
    for record in payload.get("sources", []):
        sid = record.get("source_id")
        known_hosts[sid] = {urlsplit(row[0]).hostname for row in jobs.execute(
            "SELECT DISTINCT url FROM job WHERE source_id=?", (sid,)) if urlsplit(row[0]).scheme == "https"}
    checked = _validated(payload, sources, now, known_hosts)
    report = {"accepted_sources": 0, "skipped_sources": 0, "observed_jobs": 0, "sources": []}
    # ingest_run commits each source. Stage the complete batch separately so any
    # rejection cannot leave a partially imported batch in the working databases.
    with closing(sqlite3.connect(":memory:")) as staged_jobs, \
            closing(sqlite3.connect(":memory:")) as staged_texts:
        jobs.backup(staged_jobs)
        texts.backup(staged_texts)
        staged_jobs.row_factory = sqlite3.Row
        for source, observed, values, elapsed in checked:
            latest = staged_jobs.execute(
                "SELECT ts,status,job_count FROM source_run WHERE source_id=? ORDER BY ts DESC,id DESC LIMIT 1",
                (source.id,)).fetchone()
            if latest and latest["ts"] >= observed:
                identical = latest["ts"] == observed and latest["status"] == "ok" and latest["job_count"] == len(values)
                if identical:
                    for job in values:
                        row = staged_jobs.execute(
                            "SELECT j.content_hash,j.last_seen,c.name,j.apply_end FROM job j JOIN company c "
                            "ON c.id=j.company_id WHERE j.id=?", (job.id,)).fetchone()
                        if row is not None and job.apply_end is None and row[3]:
                            job = job.model_copy(update={"apply_end": row[3]})
                        if row is None or tuple(row)[:3] != (job.content_hash(), observed, job.company):
                            identical = False
                            break
                if not identical:
                    raise ValueError("a newer or conflicting observation already exists")
                report["skipped_sources"] += 1
                continue
            result = ingest_run(staged_jobs, source.id, values, ts=observed,
                                allow_empty=False, expected_max=_expected_max(source), duration_s=elapsed)
            if result.status != "ok":
                raise ValueError("observation rejected by existing ingest safeguards")
            upsert_texts(staged_texts, values, ts=observed)
            report["accepted_sources"] += 1
            report["observed_jobs"] += len(values)
            report["sources"].append({"source_id": source.id, "observed_at": observed,
                                      "jobs": len(values), "status": result.status})
        if report["accepted_sources"]:
            staged_jobs.backup(jobs)
            staged_texts.backup(texts)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--sources", default="sources", type=Path)
    args = parser.parse_args()
    value = args.payload.read_bytes()
    if len(value) > 50 * 1024 * 1024 or hashlib.sha256(value).hexdigest() != args.sha256:
        raise ValueError("observation size or SHA-256 mismatch")
    if value.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(value)) as stream:
            value = stream.read(50 * 1024 * 1024 + 1)
        if len(value) > 50 * 1024 * 1024:
            raise ValueError("decoded observation exceeds size limit")
    for name in ("jobs.db", "jd_text.db"):
        if not (args.home / name).is_file():
            raise ValueError("recovery requires existing snapshot copies")
    with closing(connect(args.home / "jobs.db", "jobs", defer_search_index=True)) as jobs, \
            closing(connect(args.home / "jd_text.db", "text", defer_search_index=True)) as texts:
        report = apply_observations(jobs, texts, json.loads(value), load_sources(args.sources), now=now_ts())
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
