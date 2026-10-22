"""招聘日历构建：人工条目（calendar/entries/*.yaml）+ 数据层自动生成 -> calendar.db。

红线（tests/test_calendar.py 强制）：
- 人工条目的来源只能是官方公众号、公司官网/官方招聘站、政府平台；第三方站点一律拒绝。
- 每条必须有来源与数据时间戳；公众号推文必须写发布日期。查不到的字段留空，不编。
- 自动条目只写数据层观测到的事实：网申起止不填，只记录"观测到在招"的时间范围。
"""

import json
import re
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import yaml
from pydantic import BaseModel, field_validator, model_validator

from jobradar.adapters.base import USER_AGENT
from jobradar.models import SourceConfig

ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
VOCAB = Path(__file__).resolve().parents[3] / "taxonomy" / "calendar.yaml"
_vocab_cache: dict | None = None


def vocab() -> dict:
    global _vocab_cache
    if _vocab_cache is None:
        _vocab_cache = yaml.safe_load(VOCAB.read_text(encoding="utf-8"))
    return _vocab_cache


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _check_date(v):
    if v is None:
        return None
    v = str(v)
    date.fromisoformat(v)
    return v


class Source(BaseModel):
    type: str
    name: str
    url: str | None = None
    date: str | None = None

    _d = field_validator("date", mode="before")(_check_date)

    @model_validator(mode="after")
    def _red_lines(self):
        rules = vocab()["sources"]
        if self.type not in rules:
            raise ValueError(f"source.type 只能是 {list(rules)}，不能是 {self.type!r}")
        if self.url:
            host = _host(self.url)
            for bad in vocab()["third_party_blocklist"]:
                if _host_matches(host, bad):
                    raise ValueError(f"来源 {self.url} 是第三方站点（{bad}），不能作为来源")
            allowed = rules[self.type]
            if allowed and not any(_host_matches(host, d) for d in allowed):
                raise ValueError(f"source.type={self.type} 的链接必须来自 {allowed}，不能是 {host}")
        if self.type == "wechat" and not self.date:
            raise ValueError("公众号来源必须写推文发布日期 source.date")
        return self


class Track(BaseModel):
    direction: str
    roles: list[str] = []


class Jd(BaseModel):
    status: str
    url: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.status not in ("official_page", "blocked", "none"):
            raise ValueError("jd.status 只能是 official_page / blocked / none（linked 由数据层自动判定）")
        if self.status == "official_page" and not self.url:
            raise ValueError("jd.status=official_page 必须给出官方 JD 页 url")
        return self


class ManualEntry(BaseModel):
    id: str
    group: str
    company: str | None = None
    product: str | None = None
    grad_year: int | None = None
    project_type: str
    tracks: list[Track] = []
    apply_start: str | None = None
    apply_end: str | None = None
    cities: list[str] = []
    apply_url: str | None = None
    source: Source
    as_of: str
    jd: Jd = Jd(status="none")
    notes: str | None = None

    _d = field_validator("apply_start", "apply_end", "as_of", mode="before")(_check_date)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not ID_RE.match(v):
            raise ValueError(f"id {v!r} 只能用小写字母、数字和 -")
        return v

    @field_validator("project_type")
    @classmethod
    def _type(cls, v):
        if v not in vocab()["project_types"]:
            raise ValueError(f"project_type {v!r} 不在 taxonomy/calendar.yaml 的 project_types 中")
        return v

    @field_validator("grad_year")
    @classmethod
    def _year(cls, v):
        if v is not None and not 2020 <= v <= 2040:
            raise ValueError(f"grad_year {v} 不合理")
        return v

    @model_validator(mode="after")
    def _window(self):
        if self.apply_start and self.apply_end and self.apply_end < self.apply_start:
            raise ValueError("apply_end 早于 apply_start")
        return self


def load_manual(directory: Path) -> list[ManualEntry]:
    """读取 calendar/entries/*.yaml（文件名 _ 开头的为示例，忽略）。任何一条不合规都报错并指明文件与 id。"""
    out, seen = [], {}
    for p in sorted(Path(directory).glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for raw in doc.get("entries") or []:
            try:
                e = ManualEntry(group=doc["group"], **raw)
            except Exception as ex:
                raise ValueError(f"{p.name} / {raw.get('id')}: {ex}") from ex
            if e.id in seen:
                raise ValueError(f"条目 id 重复：{e.id}（{seen[e.id]} 与 {p.name}）")
            seen[e.id] = p.name
            out.append(e)
    return out


# ---------- 目标公司匹配 ----------

def _matches(name: str, company: str) -> bool:
    return len(name) >= 2 and len(company) >= 2 and (name in company or company in name)


def target_names(targets: dict) -> list[tuple[str, str]]:
    return [(n, sector) for sector, names in targets["sectors"].items() for n in names]


def match_targets(targets: dict, companies: set[str]) -> dict[str, list[str]]:
    """目标名 -> 数据层里匹配到的公司名。

    精确匹配（含 aliases）优先：某家公司如果精确等于某个目标（或别名），就只有它能认领这家公司，
    其他目标不能再用子串抢走。否则「京东」会把「京东方」算进来——2026-10-22 实测日历把
    京东方 366 个岗位挂在了京东名下，查询结果里的 jd_company 也是错的。
    """
    aliases = targets.get("aliases") or {}
    names = [t for t, _ in target_names(targets)]
    exact: dict[str, list[str]] = {}
    for t in names:
        keys = {t, *aliases.get(t, [])}
        for c in companies:
            if c in keys:
                exact.setdefault(c, []).append(t)
    out: dict[str, list[str]] = {t: [] for t in names}
    for c in companies:
        if c in exact:
            for t in exact[c]:
                out[t].append(c)
            continue
        for t in names:
            keys = [t, *aliases.get(t, [])]
            if any(_matches(k, c) for k in keys):
                out[t].append(c)
    return {t: sorted(v) for t, v in out.items()}


# ---------- 自动生成 ----------

PORTAL = {"campus": "campus", "intern": "intern", "social": "social"}


def portal_url(source: SourceConfig, recruit_type: str) -> str | None:
    """数据源对应的官方投递入口（用户点开就能看到岗位列表的页面）。"""
    p = source.params
    if source.adapter == "beisen":
        return f"https://{p['tenant']}.zhiye.com/{PORTAL[recruit_type]}"
    if source.adapter == "beisen_legacy":
        return f"https://{p['tenant']}.zhiye.com/{p.get('portal', 'campus')}/"
    if source.adapter == "tencent":
        return "https://careers.tencent.com/search.html"
    if source.adapter == "tencent_campus":
        return "https://join.qq.com/post.html"
    if source.adapter == "meituan":
        return f"https://zhaopin.meituan.com/web/{'social' if recruit_type == 'social' else 'campus'}"
    return None


_BATCH_TYPE = {"提前批": "提前批", "正式批": "秋招正式批", "秋招": "秋招正式批", "补录": "秋招补录", "春招": "春招"}
_INTERN = (("暑期", "暑期实习"), ("寒假", "寒假实习"), ("日常", "日常实习"))
CAMPUS_TYPES = {"提前批", "秋招正式批", "秋招补录", "春招", "校招", "校园大使"}
INTERN_TYPES = {"暑期实习", "寒假实习", "日常实习", "实习", "线上项目"}


def project_type_of(recruit_type: str, batch: str | None, title: str) -> str:
    """只用数据层已有的字段与标题中明写的词。"""
    if recruit_type == "social":
        return "社招"
    if recruit_type == "intern":
        return next((t for kw, t in _INTERN if kw in title), "实习")
    return _BATCH_TYPE.get(batch or "", "校招")


def recruit_type_of_project(project_type: str) -> str | None:
    if project_type in CAMPUS_TYPES:
        return "campus"
    if project_type in INTERN_TYPES:
        return "intern"
    if project_type == "社招":
        return "social"
    return None


def _group_of(company: str, matched: dict[str, list[str]]) -> str:
    return next((t for t, cs in matched.items() if company in cs), company)


def auto_entries(jobs_conn, sources: list[SourceConfig], targets: dict, *, as_of: str) -> list[dict]:
    by_id = {s.id: s for s in sources}
    rows = jobs_conn.execute(
        """SELECT j.source_id, c.name AS company, j.recruit_type, j.batch, j.grad_year, j.title,
                  j.category, j.subcategory, j.cities, j.first_seen, j.last_seen
           FROM job j JOIN company c ON c.id = j.company_id WHERE j.closed_at IS NULL
           ORDER BY j.first_seen, j.id""").fetchall()
    matched = match_targets(targets, {r["company"] for r in rows})
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        key = (r["source_id"], project_type_of(r["recruit_type"], r["batch"], r["title"]), r["grad_year"])
        groups[key].append(r)
    out = []
    for (sid, ptype, year), items in groups.items():
        company = items[0]["company"]
        per_dir: Counter = Counter()
        roles: dict[str, Counter] = defaultdict(Counter)
        examples: dict[str, list[str]] = defaultdict(list)
        for r in items:
            if r["category"]:
                per_dir[r["category"]] += 1
                if r["subcategory"]:
                    roles[r["category"]][r["subcategory"]] += 1
                if len(examples[r["category"]]) < 3:
                    examples[r["category"]].append(r["title"])
        cities = Counter(c for r in items for c in json.loads(r["cities"]))
        source = by_id.get(sid)
        url = portal_url(source, items[0]["recruit_type"]) if source else None
        out.append({
            "id": f"auto:{sid}:{ptype}:{year or 'na'}",
            "origin": "auto", "group_name": _group_of(company, matched), "company": company, "product": None,
            "grad_year": year, "project_type": ptype,
            "tracks": [{"direction": d, "roles": [s for s, _ in roles[d].most_common(5)], "examples": examples[d]}
                       for d, _ in per_dir.most_common()],
            "apply_start": None, "apply_end": None,
            "observed_from": min(r["first_seen"] for r in items)[:10],
            "observed_to": max(r["last_seen"] for r in items)[:10],
            "cities": [c for c, _ in cities.most_common(10)],
            "apply_url": url, "source_type": "data_layer", "source_name": f"数据层自动生成（{sid}）",
            "source_url": url, "source_date": as_of[:10], "as_of": as_of,
            "jd_status": "linked", "jd_url": None, "jd_company": company, "open_jobs": len(items), "notes": None,
        })
    return out


def _open_count(jobs_conn, companies: list[str], recruit_type: str | None) -> int:
    if not companies:
        return 0
    sql = (f"SELECT COUNT(*) FROM job j JOIN company c ON c.id=j.company_id WHERE j.closed_at IS NULL "
           f"AND c.name IN ({','.join('?' * len(companies))})")
    args = list(companies)
    if recruit_type:
        sql += " AND j.recruit_type = ?"
        args.append(recruit_type)
    return jobs_conn.execute(sql, args).fetchone()[0]


def manual_rows(entries: list[ManualEntry], jobs_conn, matched: dict[str, list[str]]) -> list[dict]:
    out = []
    for e in entries:
        data_cos = matched.get(e.group, [])
        if e.company:
            narrowed = [c for c in data_cos if _matches(e.company, c)]
            data_cos = narrowed or data_cos
        rtype = recruit_type_of_project(e.project_type)
        n = _open_count(jobs_conn, data_cos, rtype) if data_cos else 0
        linked = n > 0
        out.append({
            "id": e.id, "origin": "manual", "group_name": e.group, "company": e.company, "product": e.product,
            "grad_year": e.grad_year, "project_type": e.project_type,
            "tracks": [t.model_dump() for t in e.tracks],
            "apply_start": e.apply_start, "apply_end": e.apply_end, "observed_from": None, "observed_to": None,
            "cities": e.cities, "apply_url": e.apply_url,
            "source_type": e.source.type, "source_name": e.source.name, "source_url": e.source.url,
            "source_date": e.source.date, "as_of": e.as_of,
            "jd_status": "linked" if linked else e.jd.status, "jd_url": e.jd.url,
            "jd_company": "、".join(data_cos) if linked else None, "open_jobs": n if linked else None,
            "notes": e.notes,
        })
    return out


COLS = ["id", "origin", "group_name", "company", "product", "grad_year", "project_type", "tracks",
        "apply_start", "apply_end", "observed_from", "observed_to", "cities", "apply_url", "source_type",
        "source_name", "source_url", "source_date", "as_of", "jd_status", "jd_url", "jd_company", "open_jobs",
        "notes"]


def build(cal_conn, jobs_conn, *, manual: list[ManualEntry], sources: list[SourceConfig], targets: dict,
          ts: str) -> dict:
    """重建 entry 与 target 表（link_check 保留，用于跨天判断链接连续失败）。"""
    as_of = jobs_conn.execute("SELECT MAX(ts) FROM source_run WHERE status='ok'").fetchone()[0] or ts
    companies = {r[0] for r in jobs_conn.execute(
        "SELECT DISTINCT c.name FROM job j JOIN company c ON c.id=j.company_id WHERE j.closed_at IS NULL")}
    matched = match_targets(targets, companies)
    rows = manual_rows(manual, jobs_conn, matched) + auto_entries(jobs_conn, sources, targets, as_of=as_of)
    blocked = targets.get("blocked") or {}
    with cal_conn:
        cal_conn.execute("DELETE FROM entry")
        cal_conn.execute("DELETE FROM target")
        for r in rows:
            vals = [json.dumps(r[c], ensure_ascii=False) if c in ("tracks", "cities") else r[c] for c in COLS]
            cal_conn.execute(f"INSERT INTO entry({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})", vals)
        for name, sector in target_names(targets):
            cal_conn.execute("INSERT INTO target(name, sector, blocked_reason, data_companies) VALUES (?,?,?,?)",
                             (name, sector, blocked.get(name), json.dumps(matched[name], ensure_ascii=False)))
        n_manual = sum(r["origin"] == "manual" for r in rows)
        cal_conn.execute("INSERT INTO build(ts, manual, auto, data_as_of) VALUES (?,?,?,?)",
                         (ts, n_manual, len(rows) - n_manual, as_of))
    return {"manual": n_manual, "auto": len(rows) - n_manual}


# ---------- 链接探活 ----------

_DEAD = {404, 410}


_ACCEPT = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"


def check_links(cal_conn, client: httpx.Client, *, ts: str, sleep=time.sleep, min_interval: float = 1.0) -> dict:
    """对全部投递/JD/来源链接各发一次 GET（同一主机间隔 ≥1s，遵守各主机 robots.txt）。
    404/410 记为 dead，网络错误/其他状态记为 error；robots 禁止的链接不访问（计入 skipped_robots）。"""
    urls = sorted({u for (u,) in cal_conn.execute(
        """SELECT apply_url FROM entry UNION SELECT jd_url FROM entry UNION
           SELECT source_url FROM entry WHERE origin='manual'""") if u})
    last_hit: dict[str, float] = {}
    robots: dict[str, RobotFileParser | None] = {}
    counts = Counter()
    for url in urls:
        host = _host(url)
        if host not in robots:
            robots[host] = _robots(client, url)
        rp = robots[host]
        if rp is not None and not rp.can_fetch(USER_AGENT, url):
            counts["skipped_robots"] += 1
            continue
        wait = min_interval - (time.monotonic() - last_hit.get(host, -1e9))
        if wait > 0:
            sleep(wait)
        try:
            # 只看状态码，不下载正文（避免大文件或慢速流把探活拖住）
            with client.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": _ACCEPT},
                               follow_redirects=True) as r:
                code = r.status_code
            status = "ok" if code < 400 else ("dead" if code in _DEAD else "error")
        except httpx.HTTPError:
            code, status = None, "error"
        last_hit[host] = time.monotonic()
        counts[status] += 1
        prev = cal_conn.execute("SELECT first_failed_at FROM link_check WHERE url=?", (url,)).fetchone()
        first_failed = None if status == "ok" else ((prev and prev[0]) or ts)
        with cal_conn:
            cal_conn.execute(
                """INSERT INTO link_check(url, status, http_status, checked_at, first_failed_at) VALUES (?,?,?,?,?)
                   ON CONFLICT(url) DO UPDATE SET status=excluded.status, http_status=excluded.http_status,
                   checked_at=excluded.checked_at, first_failed_at=excluded.first_failed_at""",
                (url, status, code, ts, first_failed))
    return dict(counts)


def _robots(client: httpx.Client, url: str) -> RobotFileParser | None:
    """取主机的 robots.txt；取不到或不是文本时视为未限制（返回 None）。"""
    parts = urlsplit(url)
    try:
        r = client.get(f"{parts.scheme}://{parts.netloc}/robots.txt", headers={"User-Agent": USER_AGENT},
                       follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or "html" in r.headers.get("content-type", ""):
        return None
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp

