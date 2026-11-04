"""所有对外查询的唯一实现。CLI、MCP 都只是调用这里，不要在别处写 SQL。

约定：时间是 UTC ISO 字符串；返回 list[dict]，字段稳定（skill 依赖这些字段名）。
"""

import json
import math
import os
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, timedelta
from itertools import combinations
from typing import NamedTuple

from jobradar.aliases import match_names
from jobradar.normalize import category_labels
from jobradar.store.migrate import ensure_search_index
from jobradar.timeutil import now_ts, parse_ts, shanghai_date

_JOB_COLS = """j.id, c.name AS company, j.source_id, j.url, j.title, j.category, j.subcategory,
    j.recruit_type, j.grad_year, j.batch, j.cities, j.degree_min, j.department,
    j.apply_end, j.publish_at, j.first_seen, j.last_seen, j.closed_at"""

# 标题明确的一线岗位信号；专业岗位优先保留，不能把“导购产品实习生”当作导购员。
_PROFESSIONAL_TITLE = re.compile(
    r"研发|工程师|架构|开发|算法|数据|产品|设计|技术|系统|财务|会计|审计|税务|法务|人力|HRBP|"
    r"供应链|采购|战略|培训师|培训经理|总部|电商|天猫|淘宝|网店|京东|直播", re.I)
_FRONTLINE_TITLE = re.compile(
    r"咖啡师|调茶师|店员|营业员|导购|收银|店长|店经理|门店主管|值班主管|餐厅服务员|餐饮服务员|"
    r"门店(?:运营|实习|兼职|全职|储备|用工|伙伴)|置业顾问|(?:房产|地产|置业|租赁).{0,12}经纪(?:人|顾问)|"
    r"店.{0,40}(?:转介绍|诚聘合作伙伴)", re.I)


def _frontline_title(title):
    return int(bool(title and _FRONTLINE_TITLE.search(title) and not _PROFESSIONAL_TITLE.search(title)))

# 只映射范围相同的具体职类；不把「财务」放宽成包含人事、行政的整个职能大类。
_CATEGORY_ALIASES = {"财务": "财务审计", "会计": "财务审计", "审计": "财务审计",
                     "backend": "后端", "frontend": "前端", "hr": "人力"}
EVENT_TYPES = frozenset({"open", "close", "change", "reopen"})


def _text_list(values, name):
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or len(values) > 100:
        raise ValueError(f"{name} 必须是最多100项的文本列表")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 256 for v in values):
        raise ValueError(f"{name} 每项必须是1至256字符的非空文本")
    return list(dict.fromkeys(v.strip() for v in values))


def category_vocabulary(conn):
    """随安装包分发的固定职类词表；旧平台原值不改变检索词义。"""
    categories, subcategories = category_labels()
    return sorted(categories | subcategories)


def _category_match(conn, term):
    available = category_vocabulary(conn)
    normalized = _norm_name(term)
    alias = _CATEGORY_ALIASES.get(normalized)
    canonical = {_norm_name(value): value for value in available}
    target = alias or canonical.get(normalized)
    if target is not None and target in available:
        # 已登记的等价旧值也参与并集；平台出现一个“财务”原值不能覆盖“财务审计”。
        legacy = sorted(name for name, value in _CATEGORY_ALIASES.items() if value == target)
        return {"match": "alias" if alias else "exact", "matched": [target, *legacy], "input": term}
    return {"match": "none", "matched": [], "available": available}


def positive(value, name="limit"):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    if value > 1_000_000:
        raise ValueError(f"{name} 不能超过 1000000")
    return value


def lookback_since(days, *, now=None):
    positive(days, "days")
    if days > 3660:
        raise ValueError("days 不能超过 3660")
    return (parse_ts(now or now_ts()) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _filter_domains(grad_year=None, recruit_type=None):
    if grad_year is not None and (not isinstance(grad_year, int) or isinstance(grad_year, bool) or not 1000 <= grad_year <= 9999):
        raise ValueError("grad_year 必须是四位年份")
    if recruit_type is not None and recruit_type not in {"campus", "intern", "social"}:
        raise ValueError("recruit_type 必须是 campus、intern 或 social")


def current_job_condition(alias="j"):
    if alias not in {"j", ""}:
        raise ValueError("invalid SQL alias")
    prefix = alias + "." if alias else ""
    return (f"{prefix}closed_at IS NULL AND ({prefix}apply_end IS NULL OR {prefix}apply_end >= ?)",
            shanghai_date(now_ts()))


def count_current_jobs(conn, companies, recruit_type=None):
    if not companies:
        return 0
    condition, today = current_job_condition()
    # 固定从已筛选公司开始，避免日历每个批次都扫描所有未下架岗位。
    sql = ("SELECT COUNT(*) FROM company c CROSS JOIN job j "
           "WHERE c.name IN (SELECT value FROM json_each(?)) AND j.company_id=c.id AND " + condition)
    args = [json.dumps(companies), today]
    if recruit_type:
        sql += " AND j.recruit_type=?"
        args.append(recruit_type)
    return conn.execute(sql, args).fetchone()[0]


def due_source_ids(conn, source_ids, *, hours, now=None):
    positive(hours, "stale_only_hours")
    current = parse_ts(now or now_ts())
    last_ok = dict(conn.execute("SELECT source_id, MAX(ts) FROM source_run WHERE status='ok' GROUP BY source_id"))
    return {sid for sid in source_ids if sid not in last_ok or
            (current - parse_ts(last_ok[sid])).total_seconds() >= hours * 3600}


def _date_parameter(value, name):
    if value is not None:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{name} 必须是 YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{name} 不是有效日期") from None


def _company_parameter(value):
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError("公司名不能为空")


def _job_dict(row) -> dict:
    d = dict(row)
    d["cities"] = json.loads(d["cities"])
    return d


def _cec_listing(url, recruit_type):
    if not re.fullmatch(r"https://campus\.cec\.com\.cn/position/\d+", url or ""):
        return None
    channel = {"campus": 0, "social": 1}.get(recruit_type)
    return f"https://campus.cec.com.cn/position?positionType={channel}" if channel is not None else None


def _annotate_url(row, info):
    cec_listing = False
    if row["source_id"] == "jsonportal-cec":
        # 2026-11-03官网导航与同名职位确认：详情在列表内展开，旧拼接路径为空白。
        corrected = _cec_listing(row.get("url"), row.get("recruit_type"))
        if corrected:
            row["recorded_url"], row["url"] = row["url"], corrected
            row["url_evidence_as_of"] = "2026-11-03"
            cec_listing = True
        elif re.fullmatch(r"https://campus\.cec\.com\.cn/position\?positionType=[01]", row.get("url") or ""):
            cec_listing = True
    if info.get("adapter") == "netease" or cec_listing:
        row["url_scope"] = "project_listing"
        row["url_hint"] = "链接为项目职位列表，需按岗位标题查找；不是该岗位的直接详情或申请链接"
    elif info.get("record_kind") == "recruitment_notice":
        row["url_scope"] = "source_notice"
    else:
        row["url_scope"] = "unknown"


def _source_annotations(conn, rows, *, clock=None):
    if not rows:
        return rows
    ids = sorted({row["source_id"] for row in rows})
    last_ok = dict(conn.execute(
        "SELECT source_id, MAX(ts) FROM source_run WHERE status='ok' "
        "AND source_id IN (SELECT value FROM json_each(?)) GROUP BY source_id", (json.dumps(ids),)))
    clock = clock or now_ts()
    now = parse_ts(clock)
    today = shanghai_date(clock)
    from jobradar.source_catalog import catalog

    sources = catalog()
    for row in rows:
        stamp = last_ok.get(row["source_id"])
        age = max(0, (now - parse_ts(stamp)).total_seconds() / 3600) if stamp else None
        stale = age is None or age > 48
        info = sources.get(row["source_id"], {})
        enabled = info.get("enabled")
        row.update(source_last_ok=stamp, source_age_hours=round(age, 2) if age is not None else None,
                   source_stale=stale, source_enabled=enabled,
                   availability=("closed" if row["closed_at"] else "expired" if row["apply_end"] and row["apply_end"] < today
                                 else "unconfirmed_disabled" if enabled is False
                                 else "unconfirmed_stale" if stale else "observed_recently"))
        row.update(source_kind=info.get("source_kind", "unknown"),
                   record_kind=info.get("record_kind", "unknown"))
        row["availability_label"] = {
            "closed":"已下架", "expired":"已超过记录截止日",
            "unconfirmed_disabled":"历史记录，来源已暂停采集",
            "unconfirmed_stale":"历史记录，来源超过48小时未确认",
            "observed_recently":"最近观测到，投递前仍需核实官网",
        }[row["availability"]]
        row["source_tenant_peers"] = info.get("tenant_peers", [])
        warnings = []
        if enabled is False:
            warnings.append("该来源已暂停采集，历史记录继续展示；不能据此确认当前可投，也不表示岗位已关闭")
        elif stale:
            warnings.append("该来源超过48小时未成功确认；这是历史观测，当前可投状态需核实原站")
        if row["source_tenant_peers"]:
            warnings.append("同一招聘租户还登记在其他来源下，岗位可能重复；跨来源数量不能直接相加")
        row["source_warnings"] = warnings
        _annotate_url(row, info)
    return rows


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _use_fts(conn, table: str, term: str) -> bool:
    # SQLite trigram LIKE 对 >=3 字符才有索引收益，且带 ESCAPE 时不能使用索引。
    # 百分号/下划线仍走旧的字面量匹配，不能把用户输入解释成通配符或 FTS 语法。
    if len(term) < 3 or "%" in term or "_" in term:
        return False
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        filename = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
        if not filename or os.environ.get("JOBRADAR_BUILD_SEARCH_INDEX") == "1":
            ensure_search_index(conn, table)
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(exists)


def _title_ids(conn, term: str, candidate_ids=None) -> list[str]:
    if candidate_ids is not None:
        return [r[0] for r in conn.execute(
            "SELECT id FROM job WHERE id IN (SELECT value FROM json_each(?)) AND title LIKE ? ESCAPE '\\'",
            (json.dumps(sorted(candidate_ids)), _like(term)))]
    if _use_fts(conn, "job_fts", term):
        return [r[0] for r in conn.execute(
            "SELECT id FROM job WHERE rowid IN (SELECT rowid FROM job_fts WHERE title LIKE ?)",
            (f"%{term}%",))]
    return [r[0] for r in conn.execute("SELECT id FROM job WHERE title LIKE ? ESCAPE '\\'", (_like(term),))]


def _jd_ids(text_conn, term: str, candidate_ids=None) -> list[str]:
    """JD 原文（职责 + 要求）中包含 term 的岗位 id。ASCII 不区分大小写。"""
    if candidate_ids is not None:
        return [r[0] for r in text_conn.execute(
            "SELECT job_id FROM job_text WHERE job_id IN (SELECT value FROM json_each(?)) "
            "AND (description LIKE ? ESCAPE '\\' OR requirements LIKE ? ESCAPE '\\')",
            (json.dumps(sorted(candidate_ids)), _like(term), _like(term)))]
    if _use_fts(text_conn, "job_text_fts", term):
        # 两列分别使用索引，再取并集；不用会破坏索引优化的 ESCAPE 或拼接表达式。
        return [r[0] for r in text_conn.execute(
            "SELECT job_id FROM job_text WHERE rowid IN ("
            "SELECT rowid FROM job_text_fts WHERE description LIKE ? UNION "
            "SELECT rowid FROM job_text_fts WHERE requirements LIKE ?)", (f"%{term}%", f"%{term}%"))]
    return [r[0] for r in text_conn.execute(
        "SELECT job_id FROM job_text WHERE description LIKE ? ESCAPE '\\' "
        "OR requirements LIKE ? ESCAPE '\\'", (_like(term), _like(term)))]


def _snippet(text_conn, job_id: str, terms: list[str], width: int = 40) -> tuple[str | None, str | None]:
    """返回正文命中片段和正文自身的观测时间；仅标题命中时片段为空。"""
    row = text_conn.execute("SELECT description, requirements, fetched_at FROM job_text WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        return None, None
    body = "\n".join(x for x in (row["description"], row["requirements"]) if x)
    low = body.lower()
    for t in terms:
        i = low.find(t.lower())
        if i >= 0:
            return body[max(0, i - width):i + len(t) + width].replace("\n", " "), row["fetched_at"]
    return None, row["fetched_at"]


def _qualification_evidence(row, description, requirements, observed_at):
    from jobradar.normalize import degree_min_from_jd, normalize_degree

    body = "\n".join(x for x in (description, requirements) if x)
    jd_degree = degree_min_from_jd(body)
    structured = normalize_degree(row.get("degree_min"))
    conflict = bool(structured and jd_degree and structured != jd_degree)
    excerpt = next((line.strip()[:240] for line in re.split(r"[\n。；]", body)
                    if jd_degree and jd_degree in line and any(
                        anchor in line for anchor in ("学历", "学位", "及以上", "以上", "任职", "要求"))), None)
    row["qualification_evidence"] = {
        "degree": {"structured": row.get("degree_min"), "jd": jd_degree,
                   "conflict": conflict, "excerpt": excerpt}, "text_observed_at": observed_at}
    warnings = []
    if conflict:
        warnings.append(f"学历字段「{row['degree_min']}」与正文候选要求「{jd_degree}」不一致；"
                        "不能仅凭字段判定符合或排除，需核实原始要求及正文观测时间")
    if row.get("recruit_type") == "social" and row.get("grad_year"):
        warnings.append("社招渠道也可能面向应届或毕业不久人群；渠道标签不等于投递资格，需读原文核实")
    row["field_warnings"] = warnings


def _annotate_qualifications(text_conn, rows):
    if text_conn is None or not rows:
        return
    texts = {r["job_id"]: r for r in text_conn.execute(
        "SELECT job_id,description,requirements,fetched_at FROM job_text "
        "WHERE job_id IN (SELECT value FROM json_each(?))", (json.dumps([r["id"] for r in rows]),))}
    for row in rows:
        t = texts.get(row["id"])
        _qualification_evidence(row, t["description"] if t else None,
                                t["requirements"] if t else None, t["fetched_at"] if t else None)


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
    # 已登记简称具有确定身份：全名未精确命中时，也不能用短词串到另一个集团。
    lookup = _norm_name(target) if target and not contains else t
    cands = [r for r in rows if lookup in _norm_name(r["name"])]
    cand_names = [r["name"] for r in cands]
    if contains:
        return (CompanyMatch("contains", [r["id"] for r in cands], cand_names, [], target)
                if cands else CompanyMatch("none", [], [], [], target))
    if target:
        # 登记的是确定主体；仅有子公司或相近名称时保留候选，不自动更换主体。
        return CompanyMatch("ambiguous" if len(cands) > 1 else "none", [], [], cand_names, target)
    if not cands:
        return CompanyMatch("none", [], [], [], target)
    if len(cands) == 1:
        norm = _norm_name(cands[0]["name"])
        if norm.startswith(lookup) and len(norm) - len(lookup) <= _PREFIX_TAIL_GUESS_LIMIT:
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
                dedupe=False, exclude_store=False, deadline_before=None,
                deadline_after=None, cities=None, exclude_cities=None,
                exclude_keywords=None, exclude_companies=None,
                include_unknown_grad_year=False, include_frontline=False,
                exclude_categories=None) -> list[dict]:
    """keyword 只匹配标题；text 为全文检索：空格分隔的每个词都须出现在标题或 JD 原文中（需要 text_conn）。

    meta 传入 dict 时写入 `company_match`（命中方式/候选），供 CLI/MCP 回显"这是猜的还是确定的"。
    dedupe=True 时把「同公司+同标题+同城市」的多条 req 折叠成一条，并给出 `variants`（原条数）。
    校招和实习查询默认过滤明确的一线门店、房产经纪标题，include_frontline=True可主动包含。
    exclude_store=True可对其他类型主动过滤；exclude_categories按固定职类及其已登记旧值排除。
    """
    where, args, predicates = [], [], []
    def add(clause, *values, field=None):
        where.append(clause)
        args.extend(values)
        predicates.append((clause, values, field))

    positive(limit)
    if type(include_frontline) is not bool or type(exclude_store) is not bool:
        raise ValueError("include_frontline 与 exclude_store 必须为布尔值")
    if include_frontline and exclude_store:
        raise ValueError("include_frontline 与 exclude_store 不能同时使用")
    _filter_domains(grad_year, recruit_type)
    _company_parameter(company)
    if category is not None and (not isinstance(category, str) or not category.strip()):
        raise ValueError("职类必须是非空文本")
    _date_parameter(deadline_before, "deadline_before")
    _date_parameter(deadline_after, "deadline_after")
    if deadline_before and deadline_after and deadline_before < deadline_after:
        raise ValueError("截止日范围起止颠倒")
    cities = _text_list(cities, "cities")
    exclude_cities = _text_list(exclude_cities, "exclude_cities")
    exclude_keywords = _text_list(exclude_keywords, "exclude_keywords")
    exclude_companies = _text_list(exclude_companies, "exclude_companies")
    exclude_categories = _text_list(exclude_categories, "exclude_categories")
    if city and cities:
        raise ValueError("city 与 cities 不能同时指定；多城市使用 cities")
    if city is not None and (not isinstance(city, str) or not city.strip()):
        raise ValueError("city 必须是非空文本")
    if include_unknown_grad_year and grad_year is None:
        raise ValueError("include_unknown_grad_year 需要同时指定 grad_year")
    clock = now_ts()
    today = shanghai_date(clock)
    if meta is not None:
        meta.update(total=0, returned=0, truncated=False, empty_reason=None)
        # 调用方可复用同一个字典，上一轮筛选信息不能泄漏到下一轮。
        for key in ("company_match", "company_coverage", "category_match", "filter_coverage", "hints",
                    "excluded_company_matches", "text_match_semantics", "excluded_category_matches", "frontline_filter"):
            meta.pop(key, None)
    if not include_closed:
        add("j.closed_at IS NULL")
        # 快照可能早于今天：明示截止日一过就从当前岗位中隐藏，无需等该源再次成功抓取。
        # 这是查询过滤，不改 closed_at / miss_count，失败与拒收仍不能改变岗位状态。
        add("(j.apply_end IS NULL OR j.apply_end >= ?)", today)
    frontline_mode = ("exclude" if exclude_store else "include" if include_frontline else
                      "auto_campus_intern" if recruit_type in {"campus", "intern"} else "off")
    frontline_clause = None
    if frontline_mode in {"exclude", "auto_campus_intern"}:
        conn.create_function("jobradar_frontline", 1, _frontline_title, deterministic=True)
        frontline_clause = "jobradar_frontline(j.title)=0"
    if company:
        match = resolve_company(conn, company, contains=contains)
        clause, company_args = _company_sql(match)
        add(clause, *company_args)
        if meta is not None:
            meta["company_match"] = match.as_meta()
    if category:
        category_match = _category_match(conn, category)
        values = json.dumps(category_match["matched"])
        add("(j.category COLLATE NOCASE IN (SELECT value FROM json_each(?)) "
            "OR j.subcategory COLLATE NOCASE IN (SELECT value FROM json_each(?)))", values, values)
        if meta is not None:
            meta["category_match"] = category_match
    excluded_categories = {}
    for term in exclude_categories:
        matched = _category_match(conn, term)
        if not matched["matched"]:
            raise ValueError(f"不支持排除职类「{term}」，请使用固定职类词表")
        excluded_categories[term] = matched
    if excluded_categories:
        values = json.dumps(sorted({v for match in excluded_categories.values() for v in match["matched"]}))
        add("NOT (COALESCE(j.category,'') COLLATE NOCASE IN (SELECT value FROM json_each(?)) "
            "OR COALESCE(j.subcategory,'') COLLATE NOCASE IN (SELECT value FROM json_each(?)))", values, values)
        if meta is not None:
            meta["excluded_category_matches"] = excluded_categories
    wanted_cities = [city.strip()] if city else cities
    if wanted_cities:
        labels = sorted({label for c in wanted_cities for label in (c.removesuffix("市"), c.removesuffix("市") + "市")})
        add("EXISTS (SELECT 1 FROM json_each(j.cities) WHERE value IN (SELECT value FROM json_each(?)))",
            json.dumps(labels))
    if exclude_cities:
        labels = sorted({label for c in exclude_cities for label in (c.removesuffix("市"), c.removesuffix("市") + "市")})
        add("NOT EXISTS (SELECT 1 FROM json_each(j.cities) WHERE value IN (SELECT value FROM json_each(?)))",
            json.dumps(labels))
    for word in exclude_keywords:
        add("j.title NOT LIKE ? ESCAPE '\\'", _like(word))
    excluded_matches = {}
    for name in exclude_companies:
        excluded = resolve_company(conn, name)
        if excluded.mode == "ambiguous":
            raise ValueError(f"排除公司「{name}」不唯一，请写完整名称：{'、'.join(excluded.candidates)}")
        excluded_matches[name] = excluded.as_meta()
        if excluded.ids:
            clause, values = _company_sql(excluded)
            add(f"NOT ({clause})", *values)
    if meta is not None and excluded_matches:
        meta["excluded_company_matches"] = excluded_matches
    if recruit_type:
        add("j.recruit_type = ?", recruit_type)
    if grad_year:
        add("(j.grad_year = ? OR j.grad_year IS NULL)" if include_unknown_grad_year else "j.grad_year = ?",
            grad_year, field="grad_year")
    if keyword:
        add("j.title LIKE ? ESCAPE '\\'", _like(keyword))
    # 截止日筛选：只有「确实知道截止日」的岗位才参与比较。
    # 没有截止日的岗位（北森门户全部、大易的长期开放岗）不能被当成「已过期」排除，
    # 也不能被当成「还在招」放进 --deadline-after 的结果——两种都会误导用户。
    if deadline_before:
        add("j.apply_end IS NOT NULL AND j.apply_end <= ?", deadline_before, field="apply_end")
    if deadline_after:
        add("j.apply_end IS NOT NULL AND j.apply_end >= ?", deadline_after, field="apply_end")
    if frontline_clause:
        # 先按公司、城市、类型等条件缩小范围，避免对整库先做标题规则。
        add(frontline_clause, field="frontline")
    if text is not None and (not isinstance(text, str) or len(text) > 4096):
        raise ValueError("全文检索必须为不超过 4096 字符的文本")
    terms = sorted(dict.fromkeys(text.split()), key=len, reverse=True) if text else []
    if len(terms) > 16:
        raise ValueError("全文检索最多包含 16 个不同的词")
    if terms and text_conn is None:
        raise ValueError("全文检索需要 JD 原文库 jd_text.db")
    candidates = None
    scoped = False
    from_sql = " FROM job j JOIN company c ON c.id = j.company_id"
    if (terms and os.environ.get("JOBRADAR_BUILD_SEARCH_INDEX") != "1"
            and any((company, category, city, recruit_type, grad_year, keyword,
                     deadline_before, deadline_after, exclude_store, cities, exclude_cities,
                     exclude_keywords, exclude_companies, exclude_categories))):
        # 只在集合足够小时使用主键读取；较大集合继续原路径，不截断匹配结果。
        with closing(conn.execute("SELECT j.id" + from_sql + " WHERE " + " AND ".join(where), args)) as cursor:
            eligible = cursor.fetchmany(10001)
        if len(eligible) <= 10000:
            candidates = {row[0] for row in eligible}
            scoped = True
    for t in terms:
        narrowed = candidates
        if not scoped and candidates is not None and _use_fts(conn, "job_fts", t) and _use_fts(text_conn, "job_text_fts", t):
            narrowed = None  # 已有索引时复用索引；未建索引时只检查上一词留下的候选。
        matching = set(_title_ids(conn, t, narrowed)) | set(_jd_ids(text_conn, t, narrowed))
        candidates = matching if candidates is None else candidates & matching
        if not candidates:
            break
    if terms:
        add("j.id IN (SELECT value FROM json_each(?))", json.dumps(sorted(candidates)))
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order = "apply_end, " if deadline_before or deadline_after else ""
    if dedupe:
        # ATS 上同一个岗位常开成多条 req（同公司+同标题+同城市），全库实测 9.2% 是这种重复。
        # 折叠后保留最早出现的一条，并给出去重前的条数 `variants`——不改变默认查询的计数口径。
        # 城市是集合：JSON 元素顺序或重复标签不能把同岗拆成多个去重组。
        city_key = ("(SELECT json_group_array(city) FROM "
                    "(SELECT DISTINCT value AS city FROM json_each(j.cities) ORDER BY value))")
        part = (f"PARTITION BY j.company_id, j.title, {city_key}, j.recruit_type, j.grad_year, "
                "j.degree_min, j.apply_end, j.department, j.batch")
        sql = (f"SELECT * FROM (SELECT {_JOB_COLS}, COUNT(*) OVER ({part}) AS variants,"
               f" ROW_NUMBER() OVER ({part} ORDER BY j.first_seen, j.id) AS _rn"
               f"{from_sql}{where_sql})"
               f" WHERE _rn = 1 ORDER BY {order}first_seen DESC, id LIMIT ?")
    else:
        sql = f"SELECT {_JOB_COLS}{from_sql}{where_sql}"
        sql += f" ORDER BY {order}j.first_seen DESC, j.id LIMIT ?"
    rows = [_job_dict(r) for r in conn.execute(sql, [*args, limit])]
    if meta is not None:
        total = conn.execute("SELECT COUNT(*) FROM (" + sql.rsplit(" LIMIT ?", 1)[0] + ")", args).fetchone()[0]
        meta.update(total=total, returned=len(rows), truncated=total > len(rows))
        if company:
            clause, company_args = _company_sql(match)
            recorded, visible = conn.execute(
                "SELECT COUNT(*), SUM(j.closed_at IS NULL AND (j.apply_end IS NULL OR j.apply_end>=?)) "
                f"FROM job j JOIN company c ON c.id=j.company_id WHERE {clause}",
                [today, *company_args]).fetchone()
            meta["company_coverage"] = {"indexed": bool(match.ids), "recorded_jobs": recorded,
                                        "visible_jobs": visible or 0}
            if not rows:
                meta["empty_reason"] = ("company_ambiguous" if match.mode == "ambiguous" else
                                        "company_not_indexed" if not match.ids else
                                        "no_current_jobs" if not visible else "no_matching_jobs")
        elif not rows:
            meta["empty_reason"] = "no_matching_jobs"
        hints = empty_result_hints(rows, company_match=meta.get("company_match"), grad_year=grad_year, city=city)
        if terms:
            meta["text_match_semantics"] = "literal_terms"
            hints.append("关键词命中不代表满足资格：正文可能包含否定、优先或更高的最低要求，需读原文逐项核实")
        if not rows and cities:
            hints.append("城市并集没有匹配记录；这不表示这些城市没有招聘，可去掉城市条件核实未标注工作地的候选")
        if category and category_match["match"] == "none":
            hints.append(f"职类「{category}」不在支持的词表中；可用 category_match.available 选择具体职类，"
                         "或改用标题关键词/正文检索，不会自动放宽为整个大类")
        coverage = {}
        for field, label, enabled in (("grad_year", "届次", grad_year is not None),
                                       ("apply_end", "截止日", bool(deadline_before or deadline_after))):
            if not enabled:
                continue
            if terms:
                info = {"total": None, "known": None, "unknown": None, "unit": "records",
                        "scope": "not_counted_for_fulltext"}
                hints.append(f"本次{label}筛选只按已标注字段判断；正文检索未复算放宽后的缺失数量，"
                             f"不能把结果当作全部机会；可去掉{label}条件对照查询")
            else:
                scoped = [(clause, values) for clause, values, tag in predicates if tag != field]
                scoped_sql = " WHERE " + " AND ".join(clause for clause, _ in scoped) if scoped else ""
                n, known = conn.execute(
                    f"SELECT COUNT(*),COALESCE(SUM(j.{field} IS NOT NULL),0)" + from_sql + scoped_sql,
                    [v for _, values in scoped for v in values]).fetchone()
                info = {"total": n, "known": known, "unknown": n-known, "unit": "records",
                        "scope": "other_filters"}
                if n-known:
                    hints.append(f"保留其他条件、去掉{label}筛选时有{n}条记录，其中{n-known}条未标注{label}；"
                                 "未知不等于不符合，也不等于符合；记录数未折叠")
            coverage[field] = info
        if coverage:
            meta["filter_coverage"] = coverage
        if include_unknown_grad_year:
            hints.append("已同时返回届次未标注候选；grad_year_match=unknown需要另行核实，不能宣称符合届次")
        if exclude_cities:
            hints.append("排除城市按岗位列出的任一城市执行；城市缺失仍未知，不能据此保证工作地符合要求")
        if exclude_keywords:
            hints.append("排除关键词仅匹配标题字面量，不代表已排除正文中的资格要求或语义相近岗位")
        if excluded_categories:
            hints.append("职类排除只按已标注的大类、子类及登记旧值执行；职类缺失仍可能包含相关岗位，需要核实标题和原文")
        removed = 0
        scope = "other_filters"
        if frontline_clause:
            if terms:
                removed, scope = None, "not_counted_for_fulltext"
            else:
                scoped = [(clause, values) for clause, values, tag in predicates if tag != "frontline"]
                scoped_sql = " WHERE " + " AND ".join(clause for clause, _ in scoped) if scoped else " WHERE 1"
                removed = conn.execute("SELECT COUNT(*)" + from_sql + scoped_sql + f" AND NOT ({frontline_clause})",
                                       [v for _, values in scoped for v in values]).fetchone()[0]
            amount = f"{removed}条记录" if removed is not None else "符合标题规则的候选（正文检索未复算数量）"
            hints.append(f"已按标题过滤一线门店、房产经纪岗位：{amount}；标题规则不判断资格或合同性质，"
                         "需包含时使用--include-frontline（MCP: include_frontline=true）；不能与exclude_store同时使用")
        meta["frontline_filter"] = {"mode":frontline_mode, "excluded_records":removed,
                                    "unit":"records", "scope":scope}
        for name, info in excluded_matches.items():
            if info["match"] == "none":
                hints.append(f"排除公司「{name}」未精确匹配收录主体，未移除相近名称公司；需核实名称")
        if hints:
            meta["hints"] = hints
        meta["count_unit"] = "folded_groups" if dedupe else "records"
    if dedupe:
        for r in rows:
            r.pop("_rn", None)
    if terms:
        for r in rows:
            r["match"], r["text_observed_at"] = _snippet(text_conn, r["id"], terms)
    if grad_year is not None:
        for row in rows:
            row["grad_year_match"] = "unknown" if row["grad_year"] is None else "explicit"
    _annotate_qualifications(text_conn, rows)
    return _source_annotations(conn, rows, clock=clock)


def recent_changes(conn, *, since, company=None, types=None, limit=200,
                   contains=False, meta=None) -> list[dict]:
    positive(limit)
    _company_parameter(company)
    if types is not None and (not isinstance(types, (list, tuple)) or not types
            or any(not isinstance(t, str) or t not in EVENT_TYPES for t in types)):
        raise ValueError("types 必须是非空列表，可用 open、close、change、reopen；下架使用 close")
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
    sql = f"""SELECT e.ts, e.type, e.job_id, e.diff, c.name AS company, j.title, j.url, j.source_id, j.recruit_type
              FROM job_event e JOIN job j ON j.id = e.job_id JOIN company c ON c.id = j.company_id
              WHERE {' AND '.join(where)} ORDER BY e.ts DESC, e.id DESC LIMIT ?"""
    out = []
    from jobradar.source_catalog import catalog

    sources = catalog()
    for r in conn.execute(sql, [*args, limit]):
        d = dict(r)
        d["diff"] = json.loads(d["diff"]) if d["diff"] else None
        _annotate_url(d, sources.get(d["source_id"], {}))
        out.append(d)
    if meta is not None:
        total = conn.execute("SELECT COUNT(*) FROM (" + sql.rsplit(" ORDER BY", 1)[0] + ")", args).fetchone()[0]
        meta.update(total=total, returned=len(out), truncated=total > len(out))
    return out


def new_jobs_by_category(conn, *, since, limit=20, company=None, contains=False,
                         meta=None) -> list[dict]:
    """since 之后新开（open 事件）的岗位按职类计数；没有职类的归到「未分类」。

    回答"最近哪类职位新增最多"。只统计首次出现（open），不含重开（reopen）。
    company 过滤此前被静默忽略（`diff --by category --company X` 把全库数字当成 X 的，
    2026-10-24 外部评审 P0），现在会真的按公司统计。
    """
    positive(limit)
    _company_parameter(company)
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
    sql = f"""SELECT COALESCE(NULLIF(j.category, ''), '未分类') AS category, COUNT(*) AS n
           FROM job_event e JOIN job j ON j.id = e.job_id{join}
           WHERE {' AND '.join(where)}
           GROUP BY category ORDER BY n DESC, category LIMIT ?"""
    out = [{"category": r["category"], "n": r["n"]} for r in conn.execute(sql, (*args, limit))]
    if meta is not None:
        total = conn.execute("SELECT COUNT(*) FROM (" + sql.rsplit(" ORDER BY", 1)[0] + ")", args).fetchone()[0]
        meta.update(total=total, returned=len(out), truncated=total > len(out))
    return out


def company_trend(conn, company, *, until, step_days=7, contains=False, meta=None) -> list[dict]:
    """从该公司最早岗位出现之日起，每 step_days 采样一次"当日在招岗位数"，最后一个点落在 until。
    注意：按 first_seen/closed_at 还原，岗位若曾关闭又重开，中间的空档不会体现。"""
    positive(step_days, "step_days")
    if step_days > 366:
        raise ValueError("step_days 不能超过 366")
    _company_parameter(company)
    match = resolve_company(conn, company, contains=contains)
    if meta is not None:
        meta["company_match"] = match.as_meta()
    clause, args = _company_sql(match)
    rows = conn.execute(
        f"""SELECT j.first_seen, j.closed_at, j.apply_end FROM job j JOIN company c ON c.id = j.company_id
           WHERE {clause}""",
        tuple(args),
    ).fetchall()
    if not rows:
        return []
    spans = [(shanghai_date(r["first_seen"]), shanghai_date(r["closed_at"]) if r["closed_at"] else None,
              r["apply_end"]) for r in rows]
    start = date.fromisoformat(min(s for s, _, _ in spans))
    end = date.fromisoformat(shanghai_date(until))
    if start > end:
        return []
    points, p = [], start
    while p <= end:
        points.append(p)
        p += timedelta(days=step_days)
    if points[-1] != end:
        points.append(end)
    out = []
    for p in points:
        iso = p.isoformat()
        n = sum(1 for s, c, deadline in spans if s <= iso and (c is None or c > iso)
                and (deadline is None or deadline >= iso))
        out.append({"date": iso, "open": n})
    return out


def data_status(conn, *, now, stale_after_hours=48) -> list[dict]:
    """各源最近一次成功抓取的时间与是否过期。

    `stale_after_hours` 必须与 `local.STALE_HOURS`（envelope 的 stale 判断）一致：
    以前这里是 36h、envelope 是 48h，同一个数据年龄在两个命令里会给出相反的结论
    （2026-10-24 外部评审）。48h = 连续两个日报周期没成功。

    三条聚合查询搞定（以前每个源 3 条，277 个源 = 831 条，MCP 每次调用都在付这个成本）。
    """
    now_dt = parse_ts(now)
    last: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT source_id, status, ts, error, duration_s FROM ("
        "  SELECT source_id, status, ts, error, duration_s,"
        "         ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY ts DESC, id DESC) AS rn"
        "  FROM source_run) WHERE rn = 1"
    ):
        last[r["source_id"]] = dict(r)
    last_ok = {r[0]: r[1] for r in conn.execute(
        "SELECT source_id, MAX(ts) FROM source_run WHERE status='ok' GROUP BY source_id")}
    open_jobs = {r[0]: r[1] for r in conn.execute(
        "SELECT source_id, COUNT(*) FROM job WHERE closed_at IS NULL GROUP BY source_id")}
    out = []
    for sid in sorted(last):
        row = last[sid]
        ok_ts = last_ok.get(sid)
        age = (now_dt - parse_ts(ok_ts)).total_seconds() / 3600 if ok_ts else None
        out.append({
            "source_id": sid, "last_status": row["status"], "last_run": row["ts"],
            "last_ok": ok_ts, "age_hours": age, "open_jobs": open_jobs.get(sid, 0),
            "duration_s": row["duration_s"], "error": row["error"],
            "stale": age is None or age > stale_after_hours,
        })
    return out


def data_status_summary(rows, *, limit=10) -> dict:
    """把 277 行压成 agent 真正需要的东西：计数 + 有问题的源。

    原来的整表是 52KB（约 15k tokens），而 95% 的信息是"一切正常"。
    """
    problems = sorted((r for r in rows if r["stale"] or r["last_status"] != "ok"),
                      key=lambda r: (-r["open_jobs"], r.get("last_ok") or "", r["source_id"]))
    size = len(problems) if limit is None else positive(limit)
    return {
        "counts": {
            "sources": len(rows),
            "ok": sum(1 for r in rows if r["last_status"] == "ok"),
            "failed": sum(1 for r in rows if r["last_status"] == "failed"),
            "rejected": sum(1 for r in rows if r["last_status"] == "rejected"),
            "stale": sum(1 for r in rows if r["stale"]),
            "open_jobs": sum(r["open_jobs"] for r in rows),
        },
        "slowest": sorted(
            ({"source_id": r["source_id"], "duration_s": round(r["duration_s"], 1)}
             for r in rows if r["duration_s"]),
            key=lambda d: d["duration_s"], reverse=True)[:5],
        "problems": [{**r, "error": r.get("error", "")[:180] if r.get("error") else None} for r in problems[:size]],
        "omitted_problems": max(0, len(problems) - size),
        "failing": [r["source_id"] for r in problems[:size]],
        "omitted_failing": max(0, len(problems) - size),
    }


def source_freshness(rows, *, limit=10) -> dict:
    """整体快照时间不能代表每个源都已刷新；返回有界的源级新鲜度摘要。"""
    stale = sorted((r for r in rows if r["stale"]),
                   key=lambda r: (-r["open_jobs"], r["last_ok"] or "", r["source_id"]))
    size = len(stale) if limit is None else positive(limit)
    return {
        "counts": data_status_summary(rows)["counts"],
        "stale_open_jobs": sum(r["open_jobs"] for r in stale),
        "stale_sources": [{k: r[k] for k in ("source_id", "last_ok", "age_hours", "open_jobs")}
                          for r in stale[:size]],
        "omitted_stale_sources": max(0, len(stale) - size),
    }


def compare_roles(jobs_conn, text_conn, companies, category=None, *, keyword=None, text=None,
                  per_company=5, meta=None, city=None, recruit_type=None, grad_year=None,
                  include_frontline=False, exclude_categories=None) -> dict:
    """每家公司取 per_company 个同类岗位（按职类、标题关键词和/或 JD 全文）及其 JD 原文。对比由调用方（agent）完成。
    公司无匹配岗位 -> 空列表（调用方据此告知"库里没有"，不得编造）。"""
    if not category and not keyword and not text:
        raise ValueError("compare_roles needs category, keyword or text")
    positive(per_company, "per_company")
    if not isinstance(companies, (list, tuple)) or not companies:
        raise ValueError("公司列表至少提供一家公司")
    for name in companies:
        _company_parameter(name)
    out, matches, totals, filters = {}, {}, {}, {}
    for name in companies:
        search_meta = {}
        jobs = search_jobs(jobs_conn, company=name, category=category, keyword=keyword,
                           text=text, text_conn=text_conn, limit=per_company, meta=search_meta,
                           city=city, recruit_type=recruit_type, grad_year=grad_year,
                           include_frontline=include_frontline, exclude_categories=exclude_categories)
        matches[name] = search_meta["company_match"]
        totals[name] = {k: search_meta[k] for k in ("total", "returned", "truncated")}
        filters[name] = {k: search_meta[k] for k in ("frontline_filter", "hints") if k in search_meta}
        for j in jobs:
            t = text_conn.execute(
                "SELECT description, requirements, fetched_at FROM job_text WHERE job_id=?", (j["id"],)
            ).fetchone()
            j["description"] = t["description"] if t else None
            j["requirements"] = t["requirements"] if t else None
            j["text_observed_at"] = t["fetched_at"] if t else None
            _qualification_evidence(j, j["description"], j["requirements"], j["text_observed_at"])
        out[name] = jobs
    if meta is not None:
        meta.update(
            company_matches=matches,
            company_counts=totals,
            company_filters=filters,
            missing_companies=[n for n, m in matches.items() if m["match"] == "none"],
            ambiguous_companies=[n for n, m in matches.items() if m["match"] == "ambiguous"],
            no_matching_jobs=[n for n, m in matches.items() if m["matched"] and not out[n]],
        )
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
            "SELECT description, requirements, fetched_at FROM job_text WHERE job_id=?", (job_id,)
        ).fetchone()
    d["description"] = t["description"] if t else None
    d["requirements"] = t["requirements"] if t else None
    d["text_observed_at"] = t["fetched_at"] if t else None
    _qualification_evidence(d, d["description"], d["requirements"], d["text_observed_at"])
    from jobradar.source_catalog import catalog

    d["source"] = catalog().get(d["source_id"], {"source_kind":"unknown", "record_kind":"unknown"}).copy()
    return _source_annotations(jobs_conn, [d])[0]


def data_as_of(conn) -> str | None:
    """数据截至时间 = 最近一次成功抓取的时间。所有对外回答都应带上它。"""
    return conn.execute("SELECT MAX(ts) FROM source_run WHERE status='ok'").fetchone()[0]


def source_record_overlaps(conn, sources, *, minimum_overlap=3, minimum_ratio=.9, clock=None):
    """只读审计跨源重合；相同记录不是同租户或雇主归属的自动确认。"""
    positive(minimum_overlap, "minimum_overlap")
    if type(minimum_ratio) not in (int, float) or not math.isfinite(minimum_ratio) or not 0 < minimum_ratio <= 1:
        raise ValueError("minimum_ratio 必须在0到1之间，且不能为0")
    today = shanghai_date(clock or now_ts())
    records = defaultdict(set)
    counts = Counter()
    companies = defaultdict(set)
    for row in conn.execute("""SELECT j.source_id,j.source_job_id,j.title,j.recruit_type,j.cities,
            j.grad_year,j.degree_min,j.batch,j.department,j.apply_end,c.name AS company
            FROM job j JOIN company c ON c.id=j.company_id
            WHERE j.closed_at IS NULL AND (j.apply_end IS NULL OR j.apply_end>=?)""", (today,)):
        sid = row["source_id"]
        adapter = sources.get(sid, {}).get("adapter")
        if not adapter:
            continue
        key = (adapter, row["source_job_id"], row["title"], row["recruit_type"],
               tuple(sorted(set(json.loads(row["cities"])))), row["grad_year"], row["degree_min"],
               row["batch"], row["department"], row["apply_end"])
        records[key].add(sid)
        counts[sid] += 1
        companies[sid].add(row["company"])
    overlap = Counter()
    samples = defaultdict(list)
    collision_groups = 0
    for key, ids in records.items():
        if len(ids) < 2:
            continue
        collision_groups += 1
        for pair in combinations(sorted(ids), 2):
            overlap[pair] += 1
            if len(samples[pair]) < 3:
                samples[pair].append(key[1])
    pairs = []
    for (a,b), count in sorted(overlap.items(), key=lambda item:(-item[1], item[0])):
        ratio_a, ratio_b = count / counts[a], count / counts[b]
        if count < minimum_overlap or max(ratio_a, ratio_b) < minimum_ratio:
            continue
        same_tenant = b in sources[a].get("tenant_peers", [])
        pairs.append({"source_a":a, "source_b":b, "adapter":sources[a]["adapter"],
                      "companies_a":sorted(companies[a]), "companies_b":sorted(companies[b]),
                      "overlap":count, "records_a":counts[a], "records_b":counts[b],
                      "ratio_a":round(ratio_a,6), "ratio_b":round(ratio_b,6),
                      "same_configured_tenant":same_tenant,
                      "classification":"same_configured_tenant" if same_tenant else "record_overlap_candidate",
                      "sample_job_ids":sorted(samples[(a,b)])})
    return {"data_as_of":data_as_of(conn), "scope":"open_unexpired_records",
            "as_of_date":today, "collision_groups":collision_groups, "pairs":pairs,
            "minimum_overlap":minimum_overlap, "minimum_ratio":minimum_ratio,
            "notice":"岗位重合仅为待核实线索，不自动合并雇主、停用来源或修改岗位状态"}


# ---------- 招聘日历（calendar.db） ----------

BLOCKED_HINT = "{name}希望你去他们的招聘页逛一逛哦~"


def _cal_dict(r) -> dict:
    d = dict(r)
    for k in ("tracks", "cities"):
        d[k] = json.loads(d[k]) if d[k] else []
    d["source"] = {"type": d.pop("source_type"), "name": d.pop("source_name"),
                   "url": d.pop("source_url"), "date": d.pop("source_date")}
    evidence = d.get("field_evidence")
    d["field_evidence"] = json.loads(evidence) if isinstance(evidence, str) else (evidence or {})
    d["deadline_scope"] = (d["field_evidence"].get("apply_end", {}).get("scope")
                           or ("job_evidence" if d["source"]["type"] == "data_layer" else "batch")) \
        if d["apply_end"] else "unknown"
    # 提示语使用公司名，避免把招聘项目名称误写成雇主。
    d["hint"] = BLOCKED_HINT.format(name=d["group_name"]) if d["jd_status"] == "blocked" else None
    rtype = ("social" if d["project_type"] == "社招" else "campus" if d["project_type"] in {
        "提前批", "秋招正式批", "秋招补录", "春招", "校招", "校园大使"} else None)
    if corrected := _cec_listing(d.get("apply_url"), rtype):
        d["recorded_apply_url"], d["apply_url"] = d["apply_url"], corrected
        d["apply_url_scope"] = "project_listing"
    elif re.fullmatch(r"https://campus\.cec\.com\.cn/position\?positionType=[01]", d.get("apply_url") or ""):
        d["apply_url_scope"] = "project_listing"
    elif re.fullmatch(r"https://campus(?:\.game)?\.163\.com/app/job/position\?id=\d+", d.get("apply_url") or ""):
        d["apply_url_scope"] = "project_listing"
    return d


def calendar_entries(cal_conn, *, group=None, company=None, project_type=None, grad_year=None,
                     origin=None, open_on=None, has_tracks=None, has_window=None,
                     city=None, direction=None, deadline_before=None, deadline_after=None,
                     include_expired=False, limit=100, meta=None, confirmed_open_only=False) -> list[dict]:
    """日历条目。

    过滤先按**精确**匹配；没有结果再退化为子串（`--group 字节` 仍能找到「字节跳动」）。
    这样 `--group 京东` 不会把「京东方」一起带出来（2026-10-22 实测的误匹配）。
    简称也会展开：`--group 中建` 能命中「中国建筑」（映射见 taxonomy/company_aliases.yaml）。
    project_type 始终子串：`实习` 要能命中「暑期实习」「日常实习」。
    open_on=YYYY-MM-DD：返回该日**可能**在网申中的条目。带起止日期的按日期过滤；
    没写起止的也保留（否则等于把 99% 的校招藏起来），但会标 `window_status: unknown`——
    回答时不能说"确定还能投"（2026-10-24 外部评审：不加标记等于把未知当已知）。
    has_tracks/has_window：只返回「有方向」/「有网申起止」的条目（None 表示不过滤）。

    city：按城市筛。cities 是 JSON 数组存文本，用 json_each 精确比对一个元素，
    避免 `LIKE '%北京%'` 把「北京」误配到「北京市朝阳区」这类脏值上。
    direction：按方向名筛（`技术类` / `产品类` …），同样走 json_each 比 tracks 里的
    `direction` 字段，不做全文 LIKE——否则 `产品` 会命中岗位名里的「产品经理」。
    deadline_before / deadline_after：按**截止日**筛（YYYY-MM-DD）。只看 apply_end 有值的条目，
    `--deadline-before` 用来找「快截止的」，`--deadline-after` 用来排除已过的。
    没写截止日的条目**不会**被这两个筛选返回——语义是"我知道它什么时候截止，且符合范围"。
    默认按北京时间隐藏已明确截止的批次；include_expired=True 可查历史。
    显式 open_on 时以指定日期为准，不再套用今天的过期筛选。
    """
    positive(limit)
    _filter_domains(grad_year)
    if confirmed_open_only and open_on is None:
        raise ValueError("confirmed_open_only 需要同时提供 open_on 日期")
    if meta is not None:
        meta.pop("window_counts", None)
        meta.pop("hints", None)
    if origin is not None and origin not in {"manual", "auto"}:
        raise ValueError("origin 必须是 manual 或 auto")
    _company_parameter(company)
    _company_parameter(group)
    for value, label in ((open_on, "open_on"), (deadline_before, "deadline_before"), (deadline_after, "deadline_after")):
        _date_parameter(value, label)
    if deadline_before and deadline_after and deadline_before < deadline_after:
        raise ValueError("截止日范围起止颠倒")
    today = shanghai_date(now_ts())
    exact_identity_found = False
    has_evidence = bool(cal_conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entry_field_evidence'").fetchone())
    scope = "CASE WHEN source_type='data_layer' THEN 'job_evidence' ELSE 'batch' END"
    if has_evidence:
        scope = f"COALESCE(json_extract(ev.fields, '$.apply_end.scope'), {scope})"

    def run(exact: bool) -> list[dict]:
        nonlocal exact_identity_found
        where, args = [], []
        if group:
            names = match_names(group)
            op = " = ?" if exact else " LIKE ? ESCAPE '\\'"
            where.append("(" + " OR ".join(f"group_name{op}" for _ in names) + ")")
            args += [n if exact else _like(n) for n in names]
        if company:
            names = match_names(company)
            if exact:
                where.append("(" + " OR ".join(["company = ?", "product = ?", "group_name = ?"] * len(names)) + ")")
                args += [n for n in names for _ in range(3)]
            else:
                where.append("(" + " OR ".join(["company LIKE ? ESCAPE '\\'", "product LIKE ? ESCAPE '\\'", "group_name LIKE ? ESCAPE '\\'"] * len(names)) + ")")
                args += [_like(n) for n in names for _ in range(3)]
        if exact and where:
            # 精确公司只有过期条目时，也不能退化到另一家名字相似的公司。
            exact_identity_found = bool(cal_conn.execute(
                "SELECT 1 FROM entry WHERE " + " AND ".join(where) + " LIMIT 1", args).fetchone())
        if not include_expired and not open_on:
            # 数据层自动汇总取的是最早岗位截止，不能据此判定整批结束。
            where.append(f"(apply_end IS NULL OR apply_end >= ? OR ({scope}) != 'batch')")
            args.append(today)
        if project_type:
            where.append("project_type LIKE ? ESCAPE '\\'")
            args.append(_like(project_type))
        if grad_year:
            where.append("grad_year = ?")
            args.append(grad_year)
        if origin:
            where.append("origin = ?")
            args.append(origin)
        if has_tracks:
            where.append("tracks IS NOT NULL AND tracks NOT IN ('', '[]')")
        if has_window:
            # 「有网申时间」= 起止任一有值。以前要求两端都必须有，于是写着
            # 「截止 12-31、开始未公布」的批次被判定成"没有网申时间"——
            # 对用户来说恰恰相反：他知道什么时候截止，这正是最有用的一半。
            # 与 release_check.calendar_ratios 的口径保持一致。
            where.append("((apply_start IS NOT NULL AND TRIM(CAST(apply_start AS TEXT)) != '') "
                         "OR (apply_end IS NOT NULL AND TRIM(CAST(apply_end AS TEXT)) != ''))")
        if city:
            where.append(
                "EXISTS (SELECT 1 FROM json_each(entry.cities) c "
                "WHERE c.value = ? OR c.value = ?)")
            args += [city.removesuffix("市"), city.removesuffix("市") + "市"]
        if direction:
            where.append(
                "EXISTS (SELECT 1 FROM json_each(entry.tracks) t "
                "WHERE json_extract(t.value, '$.direction') LIKE ? ESCAPE '\\')")
            args.append(_like(direction))
        if deadline_before:
            where.append("apply_end IS NOT NULL AND apply_end <= ?")
            args.append(deadline_before)
        if deadline_after:
            where.append("apply_end IS NOT NULL AND apply_end >= ?")
            args.append(deadline_after)
        if (deadline_before or deadline_after) and not include_expired and not open_on:
            where.append("apply_end >= ?")
            args.append(today)
        if open_on:
            where.append("(apply_start IS NULL OR apply_start <= ?) AND "
                         f"(apply_end IS NULL OR apply_end >= ? OR ({scope}) != 'batch')")
            args += [open_on, open_on]
            if confirmed_open_only:
                where.append(f"apply_start IS NOT NULL AND apply_end IS NOT NULL AND ({scope}) = 'batch'")
        sql = "SELECT * FROM entry"
        if has_evidence:
            sql = ("SELECT entry.*, ev.fields AS field_evidence FROM entry "
                   "LEFT JOIN entry_field_evidence ev ON ev.entry_id=entry.id")
        if where:
            sql += " WHERE " + " AND ".join(where)
        if meta is not None:
            total = cal_conn.execute("SELECT COUNT(*) FROM (" + sql + ")", args).fetchone()[0]
            meta.update(total=total, truncated=total > limit, returned=min(total, limit))
        # 排序：问到「截止日」的问题就按截止日排，问到「什么时候开放」就按开放日排。
        # 原来一律按 group_name 排，`--deadline-before 2026-12-31` 会把 ABB 排在前面、
        # 而一周内截止的 TCL/三峡 沉在 200 条之后——用户在问「最紧迫的是哪个」，
        # 按字母序回答等于没回答。没有相关日期的条目排最后（NULLS LAST），不占头部。
        if deadline_before or deadline_after or (open_on and not (group or company)):
            sql += (" ORDER BY (apply_end IS NULL), apply_end, group_name, grad_year DESC, "
                    "project_type, id LIMIT ?")
        elif open_on:
            sql += (" ORDER BY (apply_start IS NULL), apply_start DESC, group_name, grad_year DESC, "
                    "project_type, id LIMIT ?")
        else:
            sql += " ORDER BY origin DESC, group_name, grad_year DESC, project_type, id LIMIT ?"
        rows = [_cal_dict(r) for r in cal_conn.execute(sql, [*args, limit])]
        if open_on:
            for d in rows:
                known = (d["apply_start"] is not None and d["apply_end"] is not None
                         and d["deadline_scope"] == "batch")
                d["window_status"] = "open" if known else "unknown"
            if meta is not None:
                known = sum(row["window_status"] == "open" for row in rows)
                unknown = len(rows)-known
                meta["window_counts"] = {"scope": "returned", "open": known, "unknown": unknown}
                if unknown:
                    meta["hints"] = [f"本次匹配{meta['total']}条日历候选，本页{len(rows)}条中{known}条有明确完整批次窗口、"
                                     f"{unknown}条窗口未知；未知候选不能直接称为当前可投，需去原页核实"]
        return rows

    if group or company:
        rows = run(exact=True)
        if rows or exact_identity_found:
            return rows
        if any(len(match_names(term)) > 1 for term in (group, company) if term):
            # 有明确别名的主体未命中时，不能把其子公司当作原主体补上。
            return rows
    return run(exact=False)


def calendar_filter_advice(cal_conn, *, city=None, direction=None, **scope) -> str:
    """城市/方向筛选为空时说清楚「为什么空」。

    这两个字段只在简章或职位列表里明写时才有值，空结果里既有"确实没有"也有"没写"。
    把两者的数量摆出来，调用方才知道能不能下结论。

    措辞不带 `--city` 这种命令行写法：这段文字既给 CLI 用户看、也给 MCP 的 AI 助手看，
    对后者来说「去掉 --city 再查」是一句它做不到的指令。统一说成「去掉城市条件」。
    """
    parts = []
    if city:
        c = city.removesuffix("市")
        rows = calendar_entries(cal_conn, direction=direction, limit=1_000_000, **scope)
        n = sum(city in r["cities"] or c in r["cities"] for r in rows)
        total = len(rows)
        withcity = sum(bool(r["cities"]) for r in rows)
        if n == 0:
            parts.append(
                f"当前范围没有条目写了「{c}」这个城市。注意：只有 {withcity}/{total} 条写了城市，"
                f"所以这不等于「{c} 没有岗位」——去掉城市条件再查一次，或直接看该公司条目的入口")
        else:
            parts.append(f"「{c}」命中 {n} 条")
    if direction:
        rows = calendar_entries(cal_conn, city=city, limit=1_000_000, **scope)
        n = sum(any(direction in t.get("direction", "") for t in r["tracks"]) for r in rows)
        if n == 0:
            dirs = sorted({t["direction"] for r in rows for t in r["tracks"] if t.get("direction")})
            parts.append(f"没有「{direction}」方向。现有方向：{'、'.join(dirs)}")
    return "；".join(parts)


def calendar_supplement_hint(meta, calendar) -> str:
    if (meta.get("company_coverage") or {}).get("recorded_jobs", 0):
        return f"该公司已收录，当前筛选没有匹配岗位；日历另有 {calendar['entries']} 条批次"
    return f"岗位数据里没有，但日历里有 {calendar['entries']} 条"


def empty_result_hints(rows, *, company_match=None, grad_year=None, city=None,
                       category=None) -> list[str]:
    """结果为空时告诉调用方「下一步怎么查」。

    有结果时返回空列表。空结果最常见的两个原因是：字段没写（届别/城市/职类来自标题或 JD，
    很多岗位两处都不写）和公司名没唯一确定——不提示的话，agent 会把它们说成「没有岗位」。

    措辞里写「条件」而不是 `--flag`：这段文字同时出现在 CLI 输出和 MCP 返回给 AI 助手的
    `hints` 里，对后者「加 --contains」是它做不到的指令，只会被原样念给用户。
    """
    if rows:
        return []
    out = []
    cm = company_match or {}
    if cm.get("match") == "none":
        target = cm.get("alias_target")
        out.append((f"该名称映射到「{target}」，但该主体未收录岗位记录" if target else "该名称未收录岗位记录")
                   + "；这不表示没有招聘，可核实完整公司名或查询招聘日历")
    if cm.get("match") == "ambiguous":
        cands = "、".join(cm.get("candidates") or [])
        out.append(f"公司名没有唯一确定（{cm['match']}）" + (f"，候选：{cands}" if cands else "")
                   + "；换完整公司名，或用子串匹配再搜一次")
    for flag, label in ((grad_year, "届别"), (city, "城市"), (category, "职类")):
        if flag:
            out.append(f"按{label}筛只命中写了{label}的岗位（很多校招岗位不写届别/城市）；"
                       f"去掉{label}条件再查一次")
    return out


def calendar_hint(cal_conn, term: str) -> dict | None:
    """岗位搜不到时，把「日历里有这家公司」这件事说出来。

    背景（2026-10-24 实测）：搜「字节跳动」「华为」「小米」「招商银行」只回"数据里没有"，
    但这些公司日历里全都有条目——用户/agent 会误以为整个数据集没有它们。
    返回 None 表示日历里也没有，调用方就不用多说什么了。
    """
    if not term:
        return None
    rows = calendar_entries(cal_conn, company=term, limit=1_000_000)
    reason = calendar_blocked_reason(cal_conn, term)
    if not rows and not reason:
        return None
    types = sorted({r["project_type"] for r in rows if r.get("project_type")})
    years = sorted({r["grad_year"] for r in rows if r.get("grad_year")}, reverse=True)
    names = {_norm_name(name) for name in match_names(term)}
    flag = "group" if all(_norm_name(r["group_name"]) in names for r in rows) else "company"
    hint_term = rows[0]["group_name"] if rows and flag == "group" else term
    out = {
        "entries": len(rows),
        "grad_years": years,
        "project_types": types[:6],
        "apply_url": next((r["apply_url"] for r in rows if r.get("apply_url")), None),
        # cmd 只是「想看完整条目时在终端里怎么敲」，MCP 的 AI 助手用不上也不该照念，
        # 所以字段名写清楚用途，避免被当作用户可执行的下一步。
        "cli_hint": f"jobradar calendar --{flag} {hint_term} --table",
    }
    if reason:
        out["blocked_reason"] = reason
        out["hint"] = f"{term}希望你去他们的招聘页逛一逛哦~"
    return out


def calendar_blocked_reason(cal_conn, term: str) -> str | None:
    """查这家公司是不是「合规上做不了」的目标，返回原因（没有则 None）。

    没有条目的 blocked 目标（BOSS直聘/微博/招商蛇口…）在 `calendar --group` 里会返回空，
    用户看不出是"没数据"还是"不能做"。CLI 用这个把原因带出来。
    """
    names = match_names(term)
    identity_found = False
    for name in names:
        row = cal_conn.execute(
            "SELECT blocked_reason FROM target WHERE name = ?",
            (name,)).fetchone()
        if row:
            identity_found = True
            if row[0]:
                return row[0]
    if identity_found or len(names) > 1:
        return None
    rows = cal_conn.execute(
        "SELECT name, blocked_reason FROM target WHERE name LIKE ? ESCAPE '\\' "
        "AND COALESCE(blocked_reason,'') <> ''", (_like(term),)).fetchall()
    if len(rows) != 1:
        return None
    name = _norm_name(rows[0]["name"])
    lookup = _norm_name(term)
    if name.startswith(lookup) and len(name) - len(lookup) <= _PREFIX_TAIL_GUESS_LIMIT:
        return None
    return rows[0]["blocked_reason"]


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

    # 字段完整度：10 个用户要求的字段各自填了多少条。
    # 只报总数没用——「覆盖率 62%」看不出到底是缺截止日还是缺城市，
    # 而这两个缺口的成因完全不同（前者是源不说，后者是门户不返回城市字段）。
    total = cal_conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    def _filled(col: str) -> int:
        return cal_conn.execute(
            f"SELECT COUNT(*) FROM entry WHERE {col} IS NOT NULL "
            f"AND TRIM(CAST({col} AS TEXT)) NOT IN ('', '[]', 'null', '{{}}')").fetchone()[0]
    fields = {
        "company": _filled("company"),
        "grad_year": _filled("grad_year"),
        "project_type": _filled("project_type"),
        "tracks": _filled("tracks"),
        "apply_start": _filled("apply_start"),
        "apply_end": _filled("apply_end"),
        "cities": _filled("cities"),
        "apply_url": _filled("apply_url"),
        "source": _filled("source_name"),
        "as_of": _filled("as_of"),
    }
    # 「≥7/10 字段填满」是发布门槛用的口径，这里直接把分数给出来，省得用户自己数
    complete = cal_conn.execute(
        "SELECT COUNT(*) FROM entry WHERE "
        "(company IS NOT NULL AND TRIM(company) != '') + "
        "(grad_year IS NOT NULL) + "
        "(project_type IS NOT NULL AND TRIM(project_type) != '') + "
        "(tracks IS NOT NULL AND TRIM(tracks) NOT IN ('', '[]')) + "
        "(apply_start IS NOT NULL) + (apply_end IS NOT NULL) + "
        "(cities IS NOT NULL AND TRIM(cities) NOT IN ('', '[]')) + "
        "(apply_url IS NOT NULL AND TRIM(apply_url) != '') + "
        "(source_name IS NOT NULL AND TRIM(source_name) != '') + "
        "(as_of IS NOT NULL AND TRIM(as_of) != '') >= 7").fetchone()[0]

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
        "entries_total": total,
        "field_filled": fields,
        "entries_complete_7of10": complete,
        "field_ratio": {k: (round(v / total, 3) if total else 0.0) for k, v in fields.items()},
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


def field_coverage(jobs_conn, *, today=None) -> dict:
    """在招岗位的字段覆盖率（0~1）。让 agent 回答前知道哪些字段不可靠。

    城市/届次缺失是"来源没给"，不是"没有"——见 skill/jobradar/references/fields.md。
    """
    n, city, gy, cat, deg, campus, campus_city, campus_gy, pub, end = jobs_conn.execute("""
        SELECT COUNT(*),
               SUM(cities IS NOT NULL AND cities NOT IN ('', '[]')),
               SUM(grad_year IS NOT NULL),
               SUM(category IS NOT NULL),
               SUM(degree_min IS NOT NULL),
               SUM(recruit_type = 'campus'),
               SUM(recruit_type = 'campus' AND cities IS NOT NULL AND cities NOT IN ('', '[]')),
               SUM(recruit_type = 'campus' AND grad_year IS NOT NULL),
               SUM(publish_at IS NOT NULL),
               SUM(apply_end IS NOT NULL)
        FROM job WHERE closed_at IS NULL AND (apply_end IS NULL OR apply_end >= ?)""",
        (today or shanghai_date(now_ts()),)).fetchone()

    def ratio(x, base):
        return round((x or 0) / base, 3) if base else None

    return {"cities": ratio(city, n), "grad_year": ratio(gy, n), "category": ratio(cat, n),
            "degree_min": ratio(deg, n),
            # 日历要「网申时间: X ~ Y」这一段，所以这两个字段的覆盖率和城市一样关键：
            # 只报城市不报日期，agent 会以为日期是全的（实测全库 publish_at 只有个位数百分比）。
            "publish_at": ratio(pub, n), "apply_end": ratio(end, n),
            "campus_cities": ratio(campus_city, campus), "campus_grad_year": ratio(campus_gy, campus)}


def jd_row_coverage(jobs_conn, text_conn):
    """全部未下架岗位的正文行覆盖，不把缺失正文推断为不同代快照。"""
    ids = [r[0] for r in jobs_conn.execute("SELECT id FROM job WHERE closed_at IS NULL")]
    if not ids:
        return None
    found = 0
    for offset in range(0, len(ids), 2000):
        found += text_conn.execute("SELECT COUNT(*) FROM job_text WHERE job_id IN (SELECT value FROM json_each(?))",
                                  (json.dumps(ids[offset:offset + 2000]),)).fetchone()[0]
    return found / len(ids)


def data_summary(jobs_conn, text_conn=None) -> dict:
    """岗位数据层概况；with_jd_text 为有 JD 正文的在招岗位数（未下载原文库时为 None）。"""
    clock = now_ts()
    today = shanghai_date(clock)
    visible = "closed_at IS NULL AND (apply_end IS NULL OR apply_end >= ?)"
    open_ids = [r[0] for r in jobs_conn.execute(f"SELECT id FROM job WHERE {visible}", (today,))]
    companies = jobs_conn.execute(
        f"SELECT COUNT(DISTINCT company_id) FROM job WHERE {visible}", (today,)).fetchone()[0]
    recorded = jobs_conn.execute("SELECT COUNT(*) FROM job WHERE closed_at IS NULL").fetchone()[0]
    with_text = None
    jd_observation = None
    if text_conn is not None:
        try:
            text_conn.execute("SELECT octet_length('')").fetchone()
        except sqlite3.OperationalError as error:
            if "no such function: octet_length" not in str(error):
                raise
            body_condition = "(COALESCE(description,'') != '' OR COALESCE(requirements,'') != '')"
        else:
            # SQLite >=3.43可从列元数据取得字节长度，避免仅为判空读取大段正文。
            # https://www.sqlite.org/lang_corefunc.html#octet_length
            body_condition = "(octet_length(description)>0 OR octet_length(requirements)>0)"
        observed = text_conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(fetched_at>=? AND fetched_at<=?),0),MIN(fetched_at),MAX(fetched_at) "
            "FROM job_text WHERE job_id IN (SELECT value FROM json_each(?)) "
            "AND " + body_condition,
            (lookback_since(2, now=clock), clock, json.dumps(open_ids))).fetchone()
        with_text = observed[0]
        jd_observation = {"fresh_48h": observed[1], "older_than_48h": with_text-observed[1],
                          "oldest": observed[2], "newest": observed[3]}
    by_type = dict(jobs_conn.execute(
        f"SELECT recruit_type, COUNT(*) FROM job WHERE {visible} GROUP BY 1", (today,)).fetchall())
    from jobradar.source_catalog import catalog

    sources = catalog()
    by_record_kind, by_source_kind = {}, {}
    for source_id, count in jobs_conn.execute(
            f"SELECT source_id, COUNT(*) FROM job WHERE {visible} GROUP BY source_id", (today,)):
        info = sources.get(source_id, {})
        record_kind, source_kind = info.get("record_kind", "unknown"), info.get("source_kind", "unknown")
        by_record_kind[record_kind] = by_record_kind.get(record_kind, 0) + count
        by_source_kind[source_kind] = by_source_kind.get(source_kind, 0) + count
    return {"open_jobs": len(open_ids), "companies": companies, "with_jd_text": with_text,
            "jd_observation": jd_observation,
            "recorded_open_jobs": recorded, "expired_hidden": recorded - len(open_ids),
            "count_as_of": today,
            "by_recruit_type": by_type,
            "category_vocabulary": category_vocabulary(jobs_conn),
            "by_record_kind": by_record_kind, "by_source_kind": by_source_kind,
            "data_as_of": data_as_of(jobs_conn), "fields": field_coverage(jobs_conn, today=today)}
