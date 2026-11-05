"""转移已读取的规范化详情进度；完整列表、访问守卫与入库检查仍在采集时执行。"""

import argparse
import gzip
import hashlib
import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from jobradar.adapters.base import load_all
from jobradar.jd_text import template_pollution
from jobradar.models import Job
from jobradar.pipeline.detail_checkpoint import (
    MAX_RECORD_BYTES,
    MAX_SOURCE_ENTRIES,
    DetailCheckpoint,
)
from jobradar.sources import load_sources
from jobradar.timeutil import now_ts, parse_ts

MAX_BYTES = 50 * 1024 ** 2


def selected_sources(sources, selected):
    configs = {s.id: s for s in sources if s.enabled}
    if (not 1 <= len(selected) <= 100 or len(set(selected)) != len(selected)
            or any(sid not in configs for sid in selected)):
        raise ValueError("必须明确选择1至100个已启用来源")
    values = [configs[sid] for sid in selected]
    if any(s.adapter not in {"hotjob", "shixiseng"}
           or type(s.params.get("detail_cache_hours")) is not int
           or not 0 < s.params["detail_cache_hours"] <= 168 for s in values):
        raise ValueError("仅转移已经启用详情进度的来源")
    return values


def export_progress(root, sources, selected, *, now):
    adapters = load_all()
    records = []
    for source in selected_sources(sources, selected):
        store = DetailCheckpoint(root, source, adapters[source.adapter], now)
        entries = []
        for value in store.load().values():
            name = hashlib.sha256(f"{source.id}:{value['source_job_id']}".encode()).hexdigest() + ".json"
            path = store.directory / name
            if path.is_symlink() or path.stat().st_size > MAX_RECORD_BYTES:
                raise ValueError("详情进度文件不安全或过大")
            entries.append(json.loads(path.read_text(encoding="utf-8")))
        if entries:
            records.append({"source_id": source.id, "entries": entries})
    return {"version": 1, "captured_at": now, "sources": records}


def _validate(payload, sources, selected, now):
    allowed = {s.id: s for s in selected_sources(sources, selected)}
    adapters = load_all()
    if (not isinstance(payload, dict) or set(payload) != {"version", "captured_at", "sources"}
            or type(payload["version"]) is not int or payload["version"] != 1):
        raise ValueError("不支持的详情进度格式")
    captured, clock = parse_ts(payload["captured_at"]), parse_ts(now)
    if captured > clock + timedelta(minutes=2):
        raise ValueError("进度导出时间晚于当前时间")
    records = payload["sources"]
    if not isinstance(records, list) or not 1 <= len(records) <= len(allowed):
        raise ValueError("详情进度来源数量不正确")
    checked, seen = [], set()
    with tempfile.TemporaryDirectory(prefix="jobradar-progress-") as directory:
        for record in records:
            if not isinstance(record, dict) or set(record) != {"source_id", "entries"}:
                raise ValueError("详情进度来源结构不正确")
            sid = record["source_id"]
            if not isinstance(sid, str) or sid not in allowed or sid in seen:
                raise ValueError("详情进度包含未选择或重复的来源")
            seen.add(sid)
            source = allowed[sid]
            entries = record["entries"]
            if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_SOURCE_ENTRIES:
                raise ValueError("详情进度数量不正确")
            store = DetailCheckpoint(directory, source, adapters[source.adapter], now)
            job_ids = set()
            for entry in entries:
                if (not isinstance(entry, dict) or set(entry) != {"version", "signature", "observed_at", "job"}
                        or not isinstance(entry["job"], dict) or set(entry["job"]) - set(Job.model_fields)):
                    raise ValueError("详情进度字段不正确")
                job = Job.model_validate(entry["job"], strict=True)
                if (job.id in job_ids or job.text_observed_at is not None
                        or job.recruit_type not in source.recruit_types
                        or not (job.description or job.requirements)
                        or any(template_pollution(v) for v in (job.description, job.requirements))
                        or parse_ts(entry["observed_at"]) > captured):
                    raise ValueError("详情进度身份、内容或时间不正确")
                job_ids.add(job.id)
                value = json.dumps(entry, ensure_ascii=False).encode("utf-8")
                if len(value) > MAX_RECORD_BYTES:
                    raise ValueError("单条详情进度过大")
                name = hashlib.sha256(job.id.encode()).hexdigest() + ".json"
                (store.directory / name).write_bytes(value)
            # 使用采集器的同一套签名、雇主、时效和容量检查，全部通过后才接触目标目录。
            if len(store.load()) != len(entries):
                raise ValueError("详情进度与当前来源、适配器或时效不一致")
            checked.append((source, adapters[source.adapter], entries))
    return checked


def import_progress(root, payload, sources, selected, *, now):
    checked = _validate(payload, sources, selected, now)
    report = {"sources": len(checked), "candidate_details": 0, "available_details": 0, "preserved_newer": 0}
    for source, adapter, entries in checked:
        store = DetailCheckpoint(root, source, adapter, now)
        current = store.load()
        for entry in entries:
            job = Job.model_validate(entry["job"], strict=True)
            report["candidate_details"] += 1
            previous = current.get(job.source_job_id)
            if previous and parse_ts(previous["fetched_at"]) >= parse_ts(entry["observed_at"]):
                report["preserved_newer"] += 1
                continue
            # 保留原详情读取时间；record已加载，不以旧时间重新清理已有进度。
            store.ts = entry["observed_at"]
            store.record(job)
        store.ts = now
        report["available_details"] += len(store.load())
    return report


def write_payload(path, payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("详情进度超出容量限制")
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    if len(compressed) > MAX_BYTES:
        raise ValueError("压缩详情进度超出容量限制")
    with Path(path).open("xb") as stream:
        stream.write(compressed)
    return hashlib.sha256(compressed).hexdigest()


def read_payload(path, sha256):
    path = Path(path)
    if path.is_symlink() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("详情进度文件不安全或过大")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("详情进度SHA-256不一致")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(MAX_BYTES + 1)
    if len(expanded) > MAX_BYTES:
        raise ValueError("解压详情进度超出容量限制")
    return json.loads(expanded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "import"))
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--sources", default="sources", type=Path)
    parser.add_argument("--only", required=True, help="明确选择的来源ID，逗号分隔")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    sources, selected, now = load_sources(args.sources), args.only.split(","), now_ts()
    if args.command == "export":
        if not args.out or args.payload or args.sha256:
            parser.error("导出仅接受--out")
        payload = export_progress(args.cache_root, sources, selected, now=now)
        _validate(payload, sources, selected, now)
        sha = write_payload(args.out, payload)
        print(json.dumps({"sha256": sha, "sources": len(payload["sources"]), "bytes": args.out.stat().st_size}))
    else:
        if not args.payload or not args.sha256 or args.out:
            parser.error("导入需要--payload及--sha256")
        payload = read_payload(args.payload, args.sha256)
        print(json.dumps(import_progress(args.cache_root, payload, sources, selected, now=now)))


if __name__ == "__main__":
    main()
