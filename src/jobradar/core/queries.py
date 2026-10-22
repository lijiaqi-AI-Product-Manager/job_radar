"""所有对外查询的唯一实现。CLI、MCP 都只是调用这里，不要在别处写 SQL。

约定：时间是 UTC ISO 字符串；返回 list[dict]，字段稳定（skill 依赖这些字段名）。
"""

import json
from datetime import date, timedelta

from jobradar.aliases import match_names
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


def _company_clause(company: str) -> tuple[str, list[str]]:
    """公司过滤：原词子串，或简称映射到的全名子串（见 aliases.py）。"""
    names = match_names(company)
    return "(" + " OR ".join(["c.name LIKE ?"] * len(names)) + ")", [f"%{n}%" for n in names]


def search_jobs(conn, *, company=None, category=None, city=None, recruit_type=None,
                grad_year=None, keyword=None, text=None, text_conn=None,
                include_closed=False, limit=50) -> list[dict]:
    """keyword 只匹配标题；text 为全文检索：空格分隔的每个词都须出现在标题或 JD 原文中（需要 text_conn）。"""
    where, args = [], []
    if not include_closed:
        where.append("j.closed_at IS NULL")
    if company:
        clause, company_args = _company_clause(company)
        where.append(clause)
        args += company_args
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
        clause, company_args = _company_clause(company)
        where.append(clause)
        args += company_args
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


def new_jobs_by_category(conn, *, since, limit=20) -> list[dict]:
    """since 之后新开（open 事件）的岗位按职类计数；没有职类的归到「未分类」。

    回答"最近哪类职位新增最多"。只统计首次出现（open），不含重开（reopen）。
    """
    rows = conn.execute(
        """SELECT COALESCE(NULLIF(j.category, ''), '未分类') AS category, COUNT(*) AS n
           FROM job_event e JOIN job j ON j.id = e.job_id
           WHERE e.type = 'open' AND e.ts >= ?
           GROUP BY category ORDER BY n DESC, category LIMIT ?""",
        (since, limit),
    )
    return [{"category": r["category"], "n": r["n"]} for r in rows]


def company_trend(conn, company, *, until, step_days=7) -> list[dict]:
    """从该公司最早岗位出现之日起，每 step_days 采样一次"当日在招岗位数"，最后一个点落在 until。
    注意：按 first_seen/closed_at 还原，岗位若曾关闭又重开，中间的空档不会体现。"""
    clause, args = _company_clause(company)
    rows = conn.execute(
        f"""SELECT j.first_seen, j.closed_at FROM job j JOIN company c ON c.id = j.company_id
           WHERE {clause}""",
        tuple(args),
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


def compare_roles(jobs_conn, text_conn, companies, category=None, *, keyword=None, text=None,
                  per_company=5) -> dict:
    """每家公司取 per_company 个同类岗位（按职类、标题关键词和/或 JD 全文）及其 JD 原文。对比由调用方（agent）完成。
    公司无匹配岗位 -> 空列表（调用方据此告知"库里没有"，不得编造）。"""
    if not category and not keyword and not text:
        raise ValueError("compare_roles needs category, keyword or text")
    out = {}
    for name in companies:
        jobs = search_jobs(jobs_conn, company=name, category=category, keyword=keyword,
                           text=text, text_conn=text_conn, limit=per_company)
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


# ---------- 招聘日历（calendar.db） ----------

BLOCKED_HINT = "{name}希望你去他们的招聘页逛一逛哦~"


def _cal_dict(r) -> dict:
    d = dict(r)
    for k in ("tracks", "cities"):
        d[k] = json.loads(d[k]) if d[k] else []
    d["source"] = {"type": d.pop("source_type"), "name": d.pop("source_name"),
                   "url": d.pop("source_url"), "date": d.pop("source_date")}
    # 提示语用公司名（用户要求："字节跳动希望你去他们的招聘页逛一逛哦~"）；
    # 用 product 会出现"管理培训生（TET）希望你去…"这种病句（2026-10-22 实测）。
    d["hint"] = BLOCKED_HINT.format(name=d["group_name"]) if d["jd_status"] == "blocked" else None
    return d


def calendar_entries(cal_conn, *, group=None, company=None, project_type=None, grad_year=None,
                     origin=None, open_on=None, limit=100) -> list[dict]:
    """日历条目。

    过滤先按**精确**匹配；没有结果再退化为子串（`--group 字节` 仍能找到「字节跳动」）。
    这样 `--group 京东` 不会把「京东方」一起带出来（2026-10-22 实测的误匹配）。
    project_type 始终子串：`实习` 要能命中「暑期实习」「日常实习」。
    open_on=YYYY-MM-DD：只返回该日处于网申窗口内的条目（没写起止的视为未知，不排除）。
    """
    def run(exact: bool) -> list[dict]:
        where, args = [], []
        if group:
            where.append("group_name = ?" if exact else "group_name LIKE ?")
            args.append(group if exact else f"%{group}%")
        if company:
            if exact:
                where.append("(company = ? OR product = ? OR group_name = ?)")
                args += [company] * 3
            else:
                where.append("(company LIKE ? OR product LIKE ? OR group_name LIKE ?)")
                args += [f"%{company}%"] * 3
        if project_type:
            where.append("project_type LIKE ?")
            args.append(f"%{project_type}%")
        if grad_year:
            where.append("grad_year = ?")
            args.append(grad_year)
        if origin:
            where.append("origin = ?")
            args.append(origin)
        if open_on:
            where.append("(apply_start IS NULL OR apply_start <= ?) AND (apply_end IS NULL OR apply_end >= ?)")
            args += [open_on, open_on]
        sql = "SELECT * FROM entry"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY origin DESC, group_name, grad_year DESC, project_type, id LIMIT ?"
        return [_cal_dict(r) for r in cal_conn.execute(sql, [*args, limit])]

    if group or company:
        rows = run(exact=True)
        if rows:
            return rows
    return run(exact=False)


def calendar_stats(cal_conn) -> dict:
    """覆盖率：目标公司中有日历条目的、有 JD（数据层关联或官方 JD 页）的。"""
    targets = cal_conn.execute("SELECT name, sector, blocked_reason, data_companies FROM target").fetchall()
    with_cal = {r[0] for r in cal_conn.execute("SELECT DISTINCT group_name FROM entry")}
    with_jd = {r[0] for r in cal_conn.execute(
        "SELECT DISTINCT group_name FROM entry WHERE jd_status IN ('linked', 'official_page')")}
    sectors: dict[str, dict] = {}
    for t in targets:
        s = sectors.setdefault(t["sector"], {"sector": t["sector"], "targets": 0, "calendar_covered": 0,
                                             "jd_covered": 0})
        s["targets"] += 1
        s["calendar_covered"] += t["name"] in with_cal
        s["jd_covered"] += t["name"] in with_jd
    origin = dict(cal_conn.execute("SELECT origin, COUNT(*) FROM entry GROUP BY 1").fetchall())
    return {
        "targets": len(targets),
        "calendar_covered": sum(t["name"] in with_cal for t in targets),
        "jd_covered": sum(t["name"] in with_jd for t in targets),
        "entries": {"manual": origin.get("manual", 0), "auto": origin.get("auto", 0)},
        "by_sector": list(sectors.values()),
        "missing_calendar": [t["name"] for t in targets if t["name"] not in with_cal],
        "jd_blocked": [{"name": t["name"], "reason": t["blocked_reason"]} for t in targets if t["blocked_reason"]],
    }


def dead_links(cal_conn, *, include_errors=False) -> list[dict]:
    """探活失败的链接及引用它们的条目。dead = 404/410；error = 网络错误或其他 4xx/5xx。"""
    statuses = ("dead", "error") if include_errors else ("dead",)
    rows = cal_conn.execute(
        f"SELECT url, status, http_status, checked_at, first_failed_at FROM link_check "
        f"WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY status, url", statuses).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["entries"] = [e[0] for e in cal_conn.execute(
            "SELECT id FROM entry WHERE apply_url=? OR jd_url=? OR source_url=? ORDER BY id", (r[0],) * 3)]
        out.append(d)
    return out


def calendar_as_of(cal_conn) -> str | None:
    row = cal_conn.execute("SELECT ts FROM build ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else None


def field_coverage(jobs_conn) -> dict:
    """在招岗位的字段覆盖率（0~1）。让 agent 回答前知道哪些字段不可靠。

    城市/届次缺失是"来源没给"，不是"没有"——见 skill/jobradar/references/fields.md。
    """
    n, city, gy, cat, deg, campus, campus_city, campus_gy = jobs_conn.execute("""
        SELECT COUNT(*),
               SUM(cities IS NOT NULL AND cities NOT IN ('', '[]')),
               SUM(grad_year IS NOT NULL),
               SUM(category IS NOT NULL),
               SUM(degree_min IS NOT NULL),
               SUM(recruit_type = 'campus'),
               SUM(recruit_type = 'campus' AND cities IS NOT NULL AND cities NOT IN ('', '[]')),
               SUM(recruit_type = 'campus' AND grad_year IS NOT NULL)
        FROM job WHERE closed_at IS NULL""").fetchone()

    def ratio(x, base):
        return round((x or 0) / base, 3) if base else None

    return {"cities": ratio(city, n), "grad_year": ratio(gy, n), "category": ratio(cat, n),
            "degree_min": ratio(deg, n),
            "campus_cities": ratio(campus_city, campus), "campus_grad_year": ratio(campus_gy, campus)}


def data_summary(jobs_conn, text_conn=None) -> dict:
    """岗位数据层概况；with_jd_text 为有 JD 正文的在招岗位数（未下载原文库时为 None）。"""
    open_ids = [r[0] for r in jobs_conn.execute("SELECT id FROM job WHERE closed_at IS NULL")]
    companies = jobs_conn.execute(
        "SELECT COUNT(DISTINCT company_id) FROM job WHERE closed_at IS NULL").fetchone()[0]
    with_text = None
    if text_conn is not None:
        with_text = text_conn.execute(
            "SELECT COUNT(*) FROM job_text WHERE job_id IN (SELECT value FROM json_each(?)) "
            "AND (COALESCE(description,'') != '' OR COALESCE(requirements,'') != '')",
            (json.dumps(open_ids),)).fetchone()[0]
    return {"open_jobs": len(open_ids), "companies": companies, "with_jd_text": with_text,
            "data_as_of": data_as_of(jobs_conn), "fields": field_coverage(jobs_conn)}
