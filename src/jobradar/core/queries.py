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


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _jd_ids(text_conn, term: str) -> list[str]:
    """JD 原文（职责 + 要求）中包含 term 的岗位 id。ASCII 不区分大小写。"""
    return [r[0] for r in text_conn.execute(
        "SELECT job_id FROM job_text WHERE COALESCE(description,'') || char(10) || COALESCE(requirements,'') "
        "LIKE ? ESCAPE '\\'", (_like(term),))]


def _snippet(text_conn, job_id: str, terms: list[str], width: int = 40) -> str | None:
    row = text_conn.execute("SELECT description, requirements FROM job_text WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        return None
    body = "\n".join(x for x in (row["description"], row["requirements"]) if x)
    low = body.lower()
    for t in terms:
        i = low.find(t.lower())
        if i >= 0:
            return body[max(0, i - width):i + len(t) + width].replace("\n", " ")
    return None


def search_jobs(conn, *, company=None, category=None, city=None, recruit_type=None,
                grad_year=None, keyword=None, text=None, text_conn=None,
                include_closed=False, limit=50) -> list[dict]:
    """keyword 只匹配标题；text 为全文检索：空格分隔的每个词都须出现在标题或 JD 原文中（需要 text_conn）。"""
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
    terms = text.split() if text else []
    if terms and text_conn is None:
        raise ValueError("全文检索需要 JD 原文库 jd_text.db")
    for t in terms:
        where.append("(j.title LIKE ? ESCAPE '\\' OR j.id IN (SELECT value FROM json_each(?)))")
        args += [_like(t), json.dumps(_jd_ids(text_conn, t))]
    sql = f"SELECT {_JOB_COLS} FROM job j JOIN company c ON c.id = j.company_id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY j.first_seen DESC, j.id LIMIT ?"
    rows = [_job_dict(r) for r in conn.execute(sql, [*args, limit])]
    if terms:
        for r in rows:
            r["match"] = _snippet(text_conn, r["id"], terms)
    return rows


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


def compare_roles(jobs_conn, text_conn, companies, category=None, *, keyword=None, per_company=5) -> dict:
    """每家公司取 per_company 个同类岗位（按职类和/或标题关键词）及其 JD 原文。对比由调用方（agent）完成。
    公司无匹配岗位 -> 空列表（调用方据此告知"库里没有"，不得编造）。"""
    if not category and not keyword:
        raise ValueError("compare_roles needs category or keyword")
    out = {}
    for name in companies:
        jobs = search_jobs(jobs_conn, company=name, category=category, keyword=keyword, limit=per_company)
        for j in jobs:
            t = text_conn.execute(
                "SELECT description, requirements FROM job_text WHERE job_id=?", (j["id"],)
            ).fetchone()
            j["description"] = t["description"] if t else None
            j["requirements"] = t["requirements"] if t else None
        out[name] = jobs
    return out


def get_job(jobs_conn, text_conn, job_id) -> dict | None:
    """单个岗位详情（含已下架的）。text_conn 为 None 表示用户没下载 JD 库，原文字段为 None。"""
    row = jobs_conn.execute(
        f"SELECT {_JOB_COLS} FROM job j JOIN company c ON c.id = j.company_id WHERE j.id = ?", (job_id,)
    ).fetchone()
    if row is None:
        return None
    d = _job_dict(row)
    t = None
    if text_conn is not None:
        t = text_conn.execute(
            "SELECT description, requirements FROM job_text WHERE job_id=?", (job_id,)
        ).fetchone()
    d["description"] = t["description"] if t else None
    d["requirements"] = t["requirements"] if t else None
    return d


def data_as_of(conn) -> str | None:
    """数据截至时间 = 最近一次成功抓取的时间。所有对外回答都应带上它。"""
    return conn.execute("SELECT MAX(ts) FROM source_run WHERE status='ok'").fetchone()[0]
