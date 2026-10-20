"""一次抓取结果 -> 数据库状态变化。

关键不变量：只有"成功且可信"的抓取才能影响岗位状态。
- 抓取失败（ok=False）：只记日志，岗位一律不动。
- 结果异常（空、或比基线骤降）：拒收并记日志，岗位一律不动。
- 岗位须在连续 close_after 次被接受的抓取中缺席才算下架。
"""

import json
from dataclasses import dataclass

from jobradar.models import Job

CLOSE_AFTER_MISSES = 3
DROP_THRESHOLD = 0.5  # 比基线少了超过 50% 视为异常
MIN_BASELINE = 10  # 基线小于此值不做骤降判断（小公司岗位数本来就波动）

STRUCT_FIELDS = (
    "url", "title", "category", "subcategory", "recruit_type",
    "grad_year", "batch", "degree_min", "department",
)


@dataclass
class RunResult:
    status: str  # ok / failed / rejected
    opened: int = 0
    closed: int = 0
    changed: int = 0
    reopened: int = 0
    reason: str | None = None


def _log_run(conn, source_id, ts, status, count, error=None):
    conn.execute(
        "INSERT INTO source_run(source_id, ts, status, job_count, error) VALUES (?,?,?,?,?)",
        (source_id, ts, status, count, error),
    )


def _event(conn, job_id, ts, type_, diff=None):
    conn.execute(
        "INSERT INTO job_event(job_id, ts, type, diff) VALUES (?,?,?,?)",
        (job_id, ts, type_, json.dumps(diff, ensure_ascii=False) if diff else None),
    )


def _company_id(conn, name):
    conn.execute("INSERT OR IGNORE INTO company(name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM company WHERE name=?", (name,)).fetchone()[0]


def _changed_fields(row, job: Job) -> list[str]:
    fields = [f for f in STRUCT_FIELDS if row[f] != getattr(job, f)]
    if sorted(json.loads(row["cities"])) != sorted(job.cities):
        fields.append("cities")
    # 哈希变了但结构化字段都没变 -> 只能是 JD 原文变了
    return fields or ["text"]


def _write_fields(conn, job: Job, ts):
    conn.execute(
        """UPDATE job SET url=?, title=?, category=?, subcategory=?, recruit_type=?, grad_year=?,
           batch=?, cities=?, degree_min=?, department=?, content_hash=? WHERE id=?""",
        (job.url, job.title, job.category, job.subcategory, job.recruit_type, job.grad_year,
         job.batch, json.dumps(job.cities, ensure_ascii=False), job.degree_min, job.department,
         job.content_hash(), job.id),
    )


def ingest_run(conn, source_id, jobs, *, ts, ok=True, error=None, allow_empty=False,
               close_after=CLOSE_AFTER_MISSES, drop_threshold=DROP_THRESHOLD,
               min_baseline=MIN_BASELINE) -> RunResult:
    if not ok:
        with conn:
            _log_run(conn, source_id, ts, "failed", 0, error)
        return RunResult("failed", reason=error)

    by_id: dict[str, Job] = {}
    for j in jobs:
        if j.source_id != source_id:
            raise ValueError(f"job {j.id} does not belong to source {source_id}")
        by_id[j.id] = j  # 同一次抓取内重复 id，后者生效

    baseline = conn.execute(
        "SELECT COUNT(*) FROM job WHERE source_id=? AND closed_at IS NULL", (source_id,)
    ).fetchone()[0]
    reason = None
    if baseline and not by_id and not allow_empty:
        reason = f"empty result but {baseline} jobs are open"
    elif baseline >= min_baseline and len(by_id) < baseline * (1 - drop_threshold):
        reason = f"job count dropped {baseline} -> {len(by_id)}"
    if reason:
        with conn:
            _log_run(conn, source_id, ts, "rejected", len(by_id), reason)
        return RunResult("rejected", reason=reason)

    res = RunResult("ok")
    with conn:
        existing = {r["id"]: r for r in conn.execute("SELECT * FROM job WHERE source_id=?", (source_id,))}
        for jid, job in by_id.items():
            row = existing.get(jid)
            h = job.content_hash()
            if row is None:
                cid = _company_id(conn, job.company)
                conn.execute(
                    """INSERT INTO job(id, company_id, source_id, source_job_id, url, title, category,
                       subcategory, recruit_type, grad_year, batch, cities, degree_min, department,
                       first_seen, last_seen, content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (jid, cid, source_id, job.source_job_id, job.url, job.title, job.category,
                     job.subcategory, job.recruit_type, job.grad_year, job.batch,
                     json.dumps(job.cities, ensure_ascii=False), job.degree_min, job.department,
                     ts, ts, h),
                )
                _event(conn, jid, ts, "open")
                res.opened += 1
                continue

            was_closed = row["closed_at"] is not None
            if h != row["content_hash"]:
                diff = {"fields": _changed_fields(row, job)}
                _write_fields(conn, job, ts)
                if not was_closed:
                    _event(conn, jid, ts, "change", diff)
                    res.changed += 1
            conn.execute(
                "UPDATE job SET last_seen=?, miss_count=0, closed_at=NULL WHERE id=?", (ts, jid)
            )
            if was_closed:
                _event(conn, jid, ts, "reopen")
                res.reopened += 1

        for jid, row in existing.items():
            if jid in by_id or row["closed_at"] is not None:
                continue
            misses = row["miss_count"] + 1
            if misses >= close_after:
                conn.execute("UPDATE job SET miss_count=?, closed_at=? WHERE id=?", (misses, ts, jid))
                _event(conn, jid, ts, "close")
                res.closed += 1
            else:
                conn.execute("UPDATE job SET miss_count=? WHERE id=?", (misses, jid))

        _log_run(conn, source_id, ts, "ok", len(by_id))
    return res


def upsert_texts(text_conn, jobs, *, ts) -> int:
    n = 0
    with text_conn:
        for j in jobs:
            if j.description is None and j.requirements is None:
                continue
            text_conn.execute(
                """INSERT INTO job_text(job_id, description, requirements, fetched_at) VALUES (?,?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET description=excluded.description,
                   requirements=excluded.requirements, fetched_at=excluded.fetched_at""",
                (j.id, j.description, j.requirements, ts),
            )
            n += 1
    return n
