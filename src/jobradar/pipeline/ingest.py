"""一次抓取结果 -> 数据库状态变化。

关键不变量：只有"成功且可信"的抓取才能影响岗位状态。
- 抓取失败（ok=False）：只记日志，岗位一律不动。
- 结果异常（空、或比基线骤降）：拒收并记日志，岗位一律不动。
- 未知截止日的岗位须在连续 close_after 次被接受的抓取中缺席才算下架；明示截止日已过可关闭。
"""

import json
from dataclasses import dataclass

from jobradar.models import Job
from jobradar.timeutil import shanghai_date

CLOSE_AFTER_MISSES = 3
DROP_THRESHOLD = 0.5  # 比基线少了超过 50% 视为异常
MIN_BASELINE = 10  # 基线小于此值不做骤降判断（小公司岗位数本来就波动）
MAX_REJECTS = 3    # 连续被骤降保护拦下 N 次后放行一次（季节结束是真的会掉一半以上）

# 参与"变更"判定的结构化字段。category/subcategory 是推导数据，不在其中（见 Job.content_hash）
STRUCT_FIELDS = (
    "url", "title", "recruit_type", "grad_year", "batch", "degree_min", "department",
    # 截止日变了是用户最该知道的变化（延长报名 / 提前截止），必须产生 changed 事件
    "apply_end",
)


@dataclass
class RunResult:
    status: str  # ok / failed / rejected
    opened: int = 0
    closed: int = 0
    changed: int = 0
    reopened: int = 0
    reason: str | None = None


def _log_run(conn, source_id, ts, status, count, error=None, duration_s=None):
    conn.execute(
        "INSERT INTO source_run(source_id, ts, status, job_count, error, duration_s) VALUES (?,?,?,?,?,?)",
        (source_id, ts, status, count, error, duration_s),
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
           batch=?, cities=?, degree_min=?, department=?, apply_end=?, publish_at=?, content_hash=?
           WHERE id=?""",
        (job.url, job.title, job.category, job.subcategory, job.recruit_type, job.grad_year,
         job.batch, json.dumps(job.cities, ensure_ascii=False), job.degree_min, job.department,
         job.apply_end, job.publish_at, job.content_hash(), job.id),
    )


def ingest_run(conn, source_id, jobs, *, ts, ok=True, error=None, allow_empty=False,
               close_after=CLOSE_AFTER_MISSES, drop_threshold=DROP_THRESHOLD,
               min_baseline=MIN_BASELINE, expected_max=None, duration_s=None) -> RunResult:
    """duration_s 记到 source_run：抓得慢的源要能从 `sources` 里看出来（以前这列永远是 NULL）。"""
    if not ok:
        with conn:
            _log_run(conn, source_id, ts, "failed", 0, error, duration_s)
        return RunResult("failed", reason=error)

    by_id: dict[str, Job] = {}
    for j in jobs:
        if j.source_id != source_id:
            raise ValueError(f"job {j.id} does not belong to source {source_id}")
        by_id[j.id] = j  # 同一次抓取内重复 id，后者生效

    baseline = conn.execute(
        "SELECT COUNT(*) FROM job WHERE source_id=? AND closed_at IS NULL", (source_id,)
    ).fetchone()[0]
    consecutive_rejects = conn.execute(
        "SELECT COUNT(*) FROM (SELECT status FROM source_run WHERE source_id=? ORDER BY id DESC LIMIT ?) "
        "WHERE status='rejected'", (source_id, MAX_REJECTS)).fetchone()[0]
    reason = None
    if baseline and not by_id and not allow_empty:
        # 空结果**永远不因「连续被拦」放行**（2026-10-24 外部评审 P0）：放行等于
        # 「源挂了 → 这家公司所有岗位都下架」，比旧岗位多挂几天糟得多。
        # 真要接受空结果（源确实清空了），必须在源配置里显式写 params.allow_empty: true。
        reason = f"empty result but {baseline} jobs are open (需要接受空结果请在源配置设 params.allow_empty)"
    elif consecutive_rejects >= MAX_REJECTS:
        # 连续多轮都是同样的骤降 → 大概率是季节结束/岗位真下架，不是抓取故障。
        # 永远拦着会让源卡死（旧岗位不下架、新岗位进不来），所以放行这一轮并记事件。
        reason = None
    elif baseline >= min_baseline and len(by_id) < baseline * (1 - drop_threshold):
        # 源设了 max_pages 限额时，历史基线可能来自「还没限额」的时候（如星巴克 18418 -> 3000）。
        # 这种情况用「限额能覆盖的最大条数」做基线，否则每次都会被骤降保护挡掉、旧岗位永远不下架。
        if expected_max and baseline > expected_max:
            baseline = expected_max
        if len(by_id) < baseline * (1 - drop_threshold):
            reason = f"job count dropped {baseline} -> {len(by_id)}"
    if reason:
        with conn:
            _log_run(conn, source_id, ts, "rejected", len(by_id), reason, duration_s)
        return RunResult("rejected", reason=reason)

    res = RunResult("ok")
    today = shanghai_date(ts)
    with conn:
        existing = {r["id"]: r for r in conn.execute("SELECT * FROM job WHERE source_id=?", (source_id,))}
        company_ids = {}
        for jid, job in by_id.items():
            row = existing.get(jid)
            if job.company not in company_ids:
                company_ids[job.company] = _company_id(conn, job.company)
            cid = company_ids[job.company]
            # 字段缺失不证明雇主延长了已知截止日；明确给出未来日期时才解除到期关闭。
            if row is not None and job.apply_end is None and row["apply_end"]:
                job = job.model_copy(update={"apply_end": row["apply_end"]})
            expired = bool(job.apply_end) and job.apply_end < today
            h = job.content_hash()
            if row is None:
                conn.execute(
                    """INSERT INTO job(id, company_id, source_id, source_job_id, url, title, category,
                       subcategory, recruit_type, grad_year, batch, cities, degree_min, department,
                       apply_end, publish_at, first_seen, last_seen, content_hash, closed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (jid, cid, source_id, job.source_job_id, job.url, job.title, job.category,
                     job.subcategory, job.recruit_type, job.grad_year, job.batch,
                     json.dumps(job.cities, ensure_ascii=False), job.degree_min, job.department,
                     job.apply_end, job.publish_at, ts, ts, h, ts if expired else None),
                )
                if not expired:
                    _event(conn, jid, ts, "open")
                    res.opened += 1
                continue

            was_closed = row["closed_at"] is not None
            company_changed = row["company_id"] != cid
            if h != row["content_hash"] or company_changed:
                fields = _changed_fields(row, job) if h != row["content_hash"] else []
                if company_changed:
                    fields.append("company")
                diff = {"fields": fields}
                if h != row["content_hash"]:
                    _write_fields(conn, job, ts)
                if not was_closed:
                    _event(conn, jid, ts, "change", diff)
                    res.changed += 1
            # 到期岗位仍然出现在列表里时，必须**保持下架**，不能顺手把它 reopen。
            # 这是第一版写的坑：`jid in by_id` 会提前 continue，导致下架分支永远走不到；
            # 改成在「已存在」分支里也判到期，并且在到期时不要 closed_at=NULL。
            conn.execute(
                "UPDATE job SET last_seen=?, miss_count=0, closed_at=?, category=?, subcategory=?, company_id=? WHERE id=?",
                (ts, (row["closed_at"] or ts) if expired else None, job.category, job.subcategory, cid, jid),
            )
            if expired and not was_closed:
                _event(conn, jid, ts, "close", {"reason": f"passed deadline {job.apply_end}"})
                res.closed += 1
            elif expired:
                pass          # 已经下架过，别重复记事件
            elif was_closed:
                _event(conn, jid, ts, "reopen")
                res.reopened += 1

        # 到期自动下架：接口给了截止日（大易 endDate），且截止日已过 = 这岗投不了了。
        # 北方华创/中车/长城汽车这类门户不会主动把过期岗位摘掉，实测 151 条截止日已过
        # 却仍是 closed_at IS NULL —— 用户搜「在招」会搜到一堆点进去显示"已截止"的岗位。
        # 判断放在「已存在」分支（见上方 expired），因为过期岗位通常仍然在列表里返回。
        for jid, row in existing.items():
            if jid in by_id or row["closed_at"] is not None:
                continue
            misses = row["miss_count"] + 1
            expired = bool(row["apply_end"]) and row["apply_end"] < today
            if expired or misses >= close_after:
                conn.execute("UPDATE job SET miss_count=?, closed_at=? WHERE id=?", (misses, ts, jid))
                diff = {"reason": f"passed deadline {row['apply_end']}"} if expired else None
                _event(conn, jid, ts, "close", diff)
                res.closed += 1
            else:
                conn.execute("UPDATE job SET miss_count=? WHERE id=?", (misses, jid))

        _log_run(conn, source_id, ts, "ok", len(by_id), duration_s=duration_s)
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
