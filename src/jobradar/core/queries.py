"""所有对外查询的唯一实现。CLI、MCP 都只是调用这里，不要在别处写 SQL。

约定：时间是 UTC ISO 字符串；返回 list[dict]，字段稳定（skill 依赖这些字段名）。
"""

import json
from datetime import date, timedelta

from jobradar.timeutil import parse_ts

_JOB_COLS = """j.id, c.name AS company, j.source_id, j.url, j.title, j.category, j.subcategory,
    j.recruit_type, j.grad_year, j.batch, j.cities, j.degree_min, j.department,
    j.first_seen, j.last_seen, j.closed_at"""


def _job_dict(row) -> dict:
    d = dict(row)
    d["cities"] = json.loads(d["cities"])
    return d


def search_jobs(conn, *, company=None, category=None, city=None, recruit_type=None,
                grad_year=None, keyword=None, include_closed=False, limit=50) -> list[dict]:
    where, args = [], []
    if not include_closed:
        where.append("j.closed_at IS NULL")
    if company:
        where.append("c.name LIKE ?")
        args.append(f"%{company}%")
    if category:
        where.append("(j.category = ? OR j.subcategory = ?)")
        args += [category, category]
    if city:
        where.append("EXISTS (SELECT 1 FROM json_each(j.cities) WHERE value = ?)")
        args.append(city)
    if recruit_type:
        where.append("j.recruit_type = ?")
        args.append(recruit_type)
    if grad_year:
        where.append("j.grad_year = ?")
        args.append(grad_year)
    if keyword:
        where.append("j.title LIKE ?")
        args.append(f"%{keyword}%")
    sql = f"SELECT {_JOB_COLS} FROM job j JOIN company c ON c.id = j.company_id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY j.first_seen DESC, j.id LIMIT ?"
    return [_job_dict(r) for r in conn.execute(sql, [*args, limit])]


def recent_changes(conn, *, since, company=None, types=None, limit=200) -> list[dict]:
    where, args = ["e.ts >= ?"], [since]
    if company:
        where.append("c.name LIKE ?")
        args.append(f"%{company}%")
    if types:
        where.append(f"e.type IN ({','.join('?' * len(types))})")
        args += list(types)
    sql = f"""SELECT e.ts, e.type, e.job_id, e.diff, c.name AS company, j.title, j.url
              FROM job_event e JOIN job j ON j.id = e.job_id JOIN company c ON c.id = j.company_id
              WHERE {' AND '.join(where)} ORDER BY e.ts DESC, e.id DESC LIMIT ?"""
    out = []
    for r in conn.execute(sql, [*args, limit]):
        d = dict(r)
        d["diff"] = json.loads(d["diff"]) if d["diff"] else None
        out.append(d)
    return out


def company_trend(conn, company, *, until, step_days=7) -> list[dict]:
    """从该公司最早岗位出现之日起，每 step_days 采样一次"当日在招岗位数"，最后一个点落在 until。
    注意：按 first_seen/closed_at 还原，岗位若曾关闭又重开，中间的空档不会体现。"""
    rows = conn.execute(
        """SELECT j.first_seen, j.closed_at FROM job j JOIN company c ON c.id = j.company_id
           WHERE c.name LIKE ?""",
        (f"%{company}%",),
    ).fetchall()
    if not rows:
        return []
    spans = [(r["first_seen"][:10], r["closed_at"][:10] if r["closed_at"] else None) for r in rows]
    start = date.fromisoformat(min(s for s, _ in spans))
    end = parse_ts(until).date()
    points, p = [], start
    while p <= end:
        points.append(p)
        p += timedelta(days=step_days)
    if points[-1] != end:
        points.append(end)
    out = []
    for p in points:
        iso = p.isoformat()
        n = sum(1 for s, c in spans if s <= iso and (c is None or c > iso))
        out.append({"date": iso, "open": n})
    return out


def data_status(conn, *, now, stale_after_hours=36) -> list[dict]:
    now_dt = parse_ts(now)
    out = []
    for r in conn.execute("SELECT DISTINCT source_id FROM source_run ORDER BY source_id"):
        sid = r["source_id"]
        last = conn.execute(
            "SELECT status, ts FROM source_run WHERE source_id=? ORDER BY ts DESC, id DESC LIMIT 1", (sid,)
        ).fetchone()
        last_ok = conn.execute(
            "SELECT MAX(ts) FROM source_run WHERE source_id=? AND status='ok'", (sid,)
        ).fetchone()[0]
        age = (now_dt - parse_ts(last_ok)).total_seconds() / 3600 if last_ok else None
        open_jobs = conn.execute(
            "SELECT COUNT(*) FROM job WHERE source_id=? AND closed_at IS NULL", (sid,)
        ).fetchone()[0]
        out.append({
            "source_id": sid, "last_status": last["status"], "last_run": last["ts"],
            "last_ok": last_ok, "age_hours": age, "open_jobs": open_jobs,
            "stale": age is None or age > stale_after_hours,
        })
    return out


def compare_roles(jobs_conn, text_conn, companies, category, *, per_company=5) -> dict:
    """每家公司取 per_company 个同类岗位及其 JD 原文。对比由调用方（agent）完成。
    公司无匹配岗位 -> 空列表（调用方据此告知"库里没有"，不得编造）。"""
    out = {}
    for name in companies:
        jobs = search_jobs(jobs_conn, company=name, category=category, limit=per_company)
        for j in jobs:
            t = text_conn.execute(
                "SELECT description, requirements FROM job_text WHERE job_id=?", (j["id"],)
            ).fetchone()
            j["description"] = t["description"] if t else None
            j["requirements"] = t["requirements"] if t else None
        out[name] = jobs
    return out
