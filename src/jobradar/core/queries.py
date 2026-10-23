"""所有对外查询的唯一实现。CLI、MCP 都只是调用这里，不要在别处写 SQL。

约定：时间是 UTC ISO 字符串；返回 list[dict]，字段稳定（skill 依赖这些字段名）。
"""

import json
import unicodedata
from datetime import date, timedelta
from typing import NamedTuple

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


class CompanyMatch(NamedTuple):
    """`--company` 的解析结果。

    mode: exact(公司名全等) / alias(简称映射命中) / contains(唯一子串) / ambiguous(命中多家) / none(没有)
    只有 ids 非空时才代表"确定是这家"，其余情况一律 0 行 + 候选，由调用方把原因告诉用户。
    """

    mode: str
    ids: list[int]
    matched: list[str] = []
    candidates: list[str] = []
    alias_target: str | None = None

    def as_meta(self) -> dict:
        d = {"match": self.mode, "matched": self.matched}
        if self.candidates:
            d["candidates"] = self.candidates
        if self.alias_target:
            d["alias_target"] = self.alias_target
        return d


# 子串匹配时，查询词只比公司名少 1 个字的"前缀延伸"更像另一家公司（京东 → 京东方），不敢猜。
_PREFIX_TAIL_GUESS_LIMIT = 1


def _norm_name(s: str) -> str:
    """公司名归一化：全半角统一、去空白、ASCII 忽略大小写（vivo / ＶＩＶＯ）。"""
    return "".join(unicodedata.normalize("NFKC", s or "").split()).casefold()


def resolve_company(conn, term: str, *, contains: bool = False) -> CompanyMatch:
    """把用户写的公司词解析成库里的公司。

    顺序：全等 → 简称映射（taxonomy/company_aliases.yaml）→ 唯一子串（`contains=True` 才放开）。
    任何一步没把握就返回 0 行 + 候选，**绝不挑一家最像的顶上**：
    2026-10-24 外部评审发现 `--company 京东` 按子串命中「京东方」，200+ 行别家岗位
    被当作京东返回且毫无提示——查询层给出的错误答案比没有答案更有害。
    """
    term = (term or "").strip()
    if not term:
        return CompanyMatch("none", [])
    rows = conn.execute("SELECT id, name FROM company ORDER BY name").fetchall()
    by_norm = {_norm_name(r["name"]): r for r in rows}
    t = _norm_name(term)
    hit = by_norm.get(t)
    if hit is not None:
        return CompanyMatch("exact", [hit["id"]], [hit["name"]])
    names = match_names(term)
    target = names[1] if len(names) > 1 else None
    if target and (hit := by_norm.get(_norm_name(target))) is not None:
        return CompanyMatch("alias", [hit["id"]], [hit["name"]], [], alias_target=target)
    cands = [r for r in rows if t in _norm_name(r["name"])]
    cand_names = [r["name"] for r in cands]
    if contains:
        return (CompanyMatch("contains", [r["id"] for r in cands], cand_names, [], target)
                if cands else CompanyMatch("none", [], [], [], target))
    if not cands:
        return CompanyMatch("none", [], [], [], target)
    if len(cands) == 1:
        norm = _norm_name(cands[0]["name"])
        if norm.startswith(t) and len(norm) - len(t) <= _PREFIX_TAIL_GUESS_LIMIT:
            return CompanyMatch("none", [], [], cand_names, target)
        return CompanyMatch("contains", [cands[0]["id"]], cand_names, [], target)
    return CompanyMatch("ambiguous", [], [], cand_names, target)


def _company_sql(match: CompanyMatch) -> tuple[str, list]:
    """把解析结果变成 SQL 片段。没确定就 `0`：宁可 0 行，也不返回别家的岗位。"""
    if not match.ids:
        return "0", []
    return "c.id IN (" + ",".join("?" * len(match.ids)) + ")", list(match.ids)

def search_jobs(conn, *, company=None, category=None, city=None, recruit_type=None,
                grad_year=None, keyword=None, text=None, text_conn=None,
                include_closed=False, limit=50, contains=False, meta=None,
                dedupe=False) -> list[dict]:
    """keyword 只匹配标题；text 为全文检索：空格分隔的每个词都须出现在标题或 JD 原文中（需要 text_conn）。

    meta 传入 dict 时写入 `company_match`（命中方式/候选），供 CLI/MCP 回显"这是猜的还是确定的"。
    dedupe=True 时把「同公司+同标题+同城市」的多条 req 折叠成一条，并给出 `variants`（原条数）。
    """
    where, args = [], []
    if not include_closed:
        where.append("j.closed_at IS NULL")
    if company:
        match = resolve_company(conn, company, contains=contains)
        clause, company_args = _company_sql(match)
        where.append(clause)
        args += company_args
        if meta is not None:
            meta["company_match"] = match.as_meta()
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
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    if dedupe:
        # ATS 上同一个岗位常开成多条 req（同公司+同标题+同城市），全库实测 9.2% 是这种重复。
        # 折叠后保留最早出现的一条，并给出去重前的条数 `variants`——不改变默认查询的计数口径。
        part = "PARTITION BY j.company_id, j.title, j.cities"
        sql = (f"SELECT * FROM (SELECT {_JOB_COLS}, COUNT(*) OVER ({part}) AS variants,"
               f" ROW_NUMBER() OVER ({part} ORDER BY j.first_seen, j.id) AS _rn"
               f" FROM job j JOIN company c ON c.id = j.company_id{where_sql})"
               " WHERE _rn = 1 ORDER BY first_seen DESC, id LIMIT ?")
    else:
        sql = f"SELECT {_JOB_COLS} FROM job j JOIN company c ON c.id = j.company_id{where_sql}"
        sql += " ORDER BY j.first_seen DESC, j.id LIMIT ?"
    rows = [_job_dict(r) for r in conn.execute(sql, [*args, limit])]
    if dedupe:
        for r in rows:
            r.pop("_rn", None)
    if terms:
        for r in rows:
            r["match"] = _snippet(text_conn, r["id"], terms)
    return rows


def recent_changes(conn, *, since, company=None, types=None, limit=200,
                   contains=False, meta=None) -> list[dict]:
    where, args = ["e.ts >= ?"], [since]
    if company:
        match = resolve_company(conn, company, contains=contains)
        clause, company_args = _company_sql(match)
        where.append(clause)
        args += company_args
        if meta is not None:
            meta["company_match"] = match.as_meta()
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


def new_jobs_by_category(conn, *, since, limit=20, company=None, contains=False,
                         meta=None) -> list[dict]:
    """since 之后新开（open 事件）的岗位按职类计数；没有职类的归到「未分类」。

    回答"最近哪类职位新增最多"。只统计首次出现（open），不含重开（reopen）。
    company 过滤此前被静默忽略（`diff --by category --company X` 把全库数字当成 X 的，
    2026-10-24 外部评审 P0），现在会真的按公司统计。
    """
    where, args = ["e.type = 'open'", "e.ts >= ?"], [since]
    join = ""
    if company:
        match = resolve_company(conn, company, contains=contains)
        clause, company_args = _company_sql(match)
        join = " JOIN company c ON c.id = j.company_id"
        where.append(clause)
        args += company_args
        if meta is not None:
            meta["company_match"] = match.as_meta()
    rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(j.category, ''), '未分类') AS category, COUNT(*) AS n
           FROM job_event e JOIN job j ON j.id = e.job_id{join}
           WHERE {' AND '.join(where)}
           GROUP BY category ORDER BY n DESC, category LIMIT ?""",
        (*args, limit),
    )
    return [{"category": r["category"], "n": r["n"]} for r in rows]


def company_trend(conn, company, *, until, step_days=7, contains=False, meta=None) -> list[dict]:
    """从该公司最早岗位出现之日起，每 step_days 采样一次"当日在招岗位数"，最后一个点落在 until。
    注意：按 first_seen/closed_at 还原，岗位若曾关闭又重开，中间的空档不会体现。"""
    match = resolve_company(conn, company, contains=contains)
    if meta is not None:
        meta["company_match"] = match.as_meta()
    clause, args = _company_sql(match)
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


def data_status(conn, *, now, stale_after_hours=48) -> list[dict]:
    """各源最近一次成功抓取的时间与是否过期。

    `stale_after_hours` 必须与 `local.STALE_HOURS`（envelope 的 stale 判断）一致：
    以前这里是 36h、envelope 是 48h，同一个数据年龄在两个命令里会给出相反的结论
    （2026-10-24 外部评审）。48h = 连续两个日报周期没成功。
    """
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
                     origin=None, open_on=None, has_tracks=None, has_window=None,
                     limit=100) -> list[dict]:
    """日历条目。

    过滤先按**精确**匹配；没有结果再退化为子串（`--group 字节` 仍能找到「字节跳动」）。
    这样 `--group 京东` 不会把「京东方」一起带出来（2026-10-22 实测的误匹配）。
    简称也会展开：`--group 中建` 能命中「中国建筑」（映射见 taxonomy/company_aliases.yaml）。
    project_type 始终子串：`实习` 要能命中「暑期实习」「日常实习」。
    open_on=YYYY-MM-DD：返回该日**可能**在网申中的条目。带起止日期的按日期过滤；
    没写起止的也保留（否则等于把 99% 的校招藏起来），但会标 `window_status: unknown`——
    回答时不能说"确定还能投"（2026-10-24 外部评审：不加标记等于把未知当已知）。
    has_tracks/has_window：只返回「有方向」/「有网申起止」的条目（None 表示不过滤）。
    """
    def run(exact: bool) -> list[dict]:
        where, args = [], []
        if group:
            names = match_names(group)
            op = " = ?" if exact else " LIKE ?"
            where.append("(" + " OR ".join(f"group_name{op}" for _ in names) + ")")
            args += [n if exact else f"%{n}%" for n in names]
        if company:
            names = match_names(company)
            if exact:
                where.append("(" + " OR ".join(["company = ?", "product = ?", "group_name = ?"] * len(names)) + ")")
                args += [n for n in names for _ in range(3)]
            else:
                where.append("(" + " OR ".join(["company LIKE ?", "product LIKE ?", "group_name LIKE ?"] * len(names)) + ")")
                args += [f"%{n}%" for n in names for _ in range(3)]
        if project_type:
            where.append("project_type LIKE ?")
            args.append(f"%{project_type}%")
        if grad_year:
            where.append("grad_year = ?")
            args.append(grad_year)
        if origin:
            where.append("origin = ?")
            args.append(origin)
        if has_tracks:
            where.append("tracks IS NOT NULL AND tracks NOT IN ('', '[]')")
        if has_window:
            where.append("apply_start IS NOT NULL AND apply_end IS NOT NULL")
        if open_on:
            where.append("(apply_start IS NULL OR apply_start <= ?) AND (apply_end IS NULL OR apply_end >= ?)")
            args += [open_on, open_on]
        sql = "SELECT * FROM entry"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY origin DESC, group_name, grad_year DESC, project_type, id LIMIT ?"
        rows = [_cal_dict(r) for r in cal_conn.execute(sql, [*args, limit])]
        if open_on:
            for d in rows:
                known = d["apply_start"] is not None and d["apply_end"] is not None
                d["window_status"] = "open" if known else "unknown"
        return rows

    if group or company:
        rows = run(exact=True)
        if rows:
            return rows
    return run(exact=False)


def empty_result_hints(rows, *, company_match=None, grad_year=None, city=None,
                       category=None) -> list[str]:
    """结果为空时告诉调用方「下一步怎么查」。

    有结果时返回空列表。空结果最常见的两个原因是：字段没写（届别/城市/职类来自标题或 JD，
    很多岗位两处都不写）和公司名没唯一确定——不提示的话，agent 会把它们说成「没有岗位」。
    """
    if rows:
        return []
    out = []
    cm = company_match or {}
    if cm.get("match") in ("none", "ambiguous"):
        cands = "、".join(cm.get("candidates") or [])
        out.append(f"公司名没有唯一确定（{cm['match']}）" + (f"，候选：{cands}" if cands else "")
                   + "；换完整公司名，或加 --contains 按子串搜")
    for flag, label in ((grad_year, "--grad-year"), (city, "--city"), (category, "--category")):
        if flag:
            out.append(f"{label} 只命中该字段有值的岗位（很多校招岗位不写届别/城市）；去掉它再查一次")
    return out


def calendar_blocked_reason(cal_conn, term: str) -> str | None:
    """查这家公司是不是「合规上做不了」的目标，返回原因（没有则 None）。

    没有条目的 blocked 目标（BOSS直聘/微博/招商蛇口…）在 `calendar --group` 里会返回空，
    用户看不出是"没数据"还是"不能做"。CLI 用这个把原因带出来。
    """
    for name in match_names(term):
        row = cal_conn.execute(
            "SELECT blocked_reason FROM target WHERE name = ? AND COALESCE(blocked_reason,'') <> ''",
            (name,)).fetchone()
        if row:
            return row[0]
    row = cal_conn.execute(
        "SELECT blocked_reason FROM target WHERE name LIKE ? AND COALESCE(blocked_reason,'') <> '' LIMIT 1",
        (f"%{term}%",)).fetchone()
    return row[0] if row else None


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
    covered_any = sum(
        1 for t in targets
        if t["name"] in with_cal or (t["data_companies"] or "[]") not in ("[]", "", None))
    return {
        "targets": len(targets),
        "calendar_covered": sum(t["name"] in with_cal for t in targets),
        # 有日历条目 或 有岗位数据：README/发布自检用的是这个口径（数据可搜到也算覆盖）
        "covered_any": covered_any,
        # 显式别名，避免和「岗位有 JD 正文的比例」混淆
        "calendar_entries_covered": sum(t["name"] in with_cal for t in targets),
        "jd_page_covered": sum(t["name"] in with_jd for t in targets),
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
    by_type = dict(jobs_conn.execute(
        "SELECT recruit_type, COUNT(*) FROM job WHERE closed_at IS NULL GROUP BY 1").fetchall())
    return {"open_jobs": len(open_ids), "companies": companies, "with_jd_text": with_text,
            "by_recruit_type": by_type,
            "data_as_of": data_as_of(jobs_conn), "fields": field_coverage(jobs_conn)}
