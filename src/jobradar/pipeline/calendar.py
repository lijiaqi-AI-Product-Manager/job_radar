"""招聘日历构建：人工条目（calendar/entries/*.yaml）+ 数据层自动生成 -> calendar.db。

红线（tests/test_calendar.py 强制）：
- 人工条目的来源只能是官方公众号、公司官网/官方招聘站、政府平台；第三方站点一律拒绝。
- 每条必须有来源与数据时间戳；公众号推文必须写发布日期。查不到的字段留空，不编。
- 自动条目只写数据层观测到的事实：网申起止不填，只记录"观测到在招"的时间范围。
"""

import json
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
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


def match_entry_company(entry: ManualEntry, companies: set[str]) -> list[str]:
    """人工条目的公司名 -> 数据层公司名（`match_targets` 之外的补充匹配）。

    为什么需要（2026-10-26 实测）：`match_targets` 只在 targets.yaml 的目标清单里做匹配，
    而人工条目里 1,474 条有 **1,150 条** 不在目标清单里 → `jd_company` 全空 →
    这些条目在日历上看不到城市、届次、JD，而数据层明明有它们的岗位。
    实测其中 **74 条** 的公司名与数据层公司名**逐字相等**（"爱尔眼科"、"阿里云"…），
    纯属白丢。

    规则（只在 `match_targets` 没匹配上时作为兜底）：
      1. 先试 `company`/`product`/`group_name` 与数据层公司名**逐字相等**（含别名）。
      2. 再试包含关系，但要求**被包含的一方 ≥3 字**。
         判的是"哪个词被包含"而不是"两个词谁短"：
         "上海蔚来汽车" ⊃ "蔚来汽车"（4 字）→ 收；"上海蔚来汽车" ⊃ "蔚来"（2 字）→ 不收；
         "华为海洋" ⊃ "华为"（2 字）→ 不收（两家公司）。
         如果按"较短一方长度"判，"上海蔚来汽车" 里的 "蔚来汽车" 会被一起误杀。
    """
    names = [n for n in (entry.company, entry.product, entry.group) if n]
    if not names:
        return []
    exact = [c for c in companies for n in names if c == n]
    if exact:
        return sorted(set(exact))
    loose = [c for c in companies for n in names if (len(c) >= 3 and c in n) or (len(n) >= 3 and n in c)]
    return sorted(set(loose))


def target_names(targets: dict) -> list[tuple[str, str]]:
    """目标名 -> 分组名。sectors 是行业口径，provinces 是省域口径（2026-10-27 新增）。

    同一家公司可能既在行业清单又在某省清单里（腾讯既在「互联网」也是广东重点企业），
    **只算一次目标**：分组取先出现的行业；省域名单保持完整，覆盖率报表按省单独统计。
    """
    out = [(n, sector) for sector, names in targets["sectors"].items() for n in names]
    seen = {n for n, _ in out}
    for prov, names in (targets.get("provinces") or {}).items():
        for n in names:
            if n not in seen:
                out.append((n, f"省域·{prov}"))
                seen.add(n)
    return out


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
                  j.category, j.subcategory, j.cities, j.first_seen, j.last_seen,
                  j.apply_end, j.publish_at
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
        # 网申时间：自动条目以前把这两项硬编码成 None，于是「数据库里有截止日、
        # 日历上却是空窗口」——同一份数据在自己的产品里丢了。这里补上，
        # 但口径和 export_job_evidence 完全一致，不做任何新推断。
        # 2026-10-26 重写（实测依据见 docs/recon/calendar-window.md）：
        #   旧口径「众数取最近」有两个硬伤——①一批里 6 条 11-30 截止、5 条 12-31 截止时
        #   会报 11-30，而「报名截止」的语义是"到这个日期之前都还能投"，取最早的完备日
        #   才是对的；②众数会在众数日期本身已过期时继续报一个过去的日期（一批里既有
        #   已过期岗位又有新一批），用户看到的是「已截止」却仍在招。
        #   新口径：apply_end = 尚未过期的最早截止日；全部过期则取最晚那天（这批整体收口日）。
        #   哨兵日期被适配器归一成 None，所以不会因为 2099 年把窗口拉长。
        ends = sorted({r["apply_end"][:10] for r in items if r["apply_end"]})
        apply_end = next((d for d in ends if d >= as_of[:10]), ends[-1] if ends else None)
        # apply_start = 多数职位的首次上架日；只有「≥3 条且占比 ≥40%」才算，
        # 单条上架日是补录日不是开放日（理由见 export_job_evidence）。
        day_votes = Counter(r["publish_at"][:10] for r in items if r["publish_at"])
        apply_start = None
        if day_votes:
            day, n = day_votes.most_common(1)[0]
            # 「同一天上架」和「同一天是截止日」同时成立，说明这批职位是**关闭那天批量补录**
            # 出来的（平台常见做法：批次下架后列表仍在，只是上架时间被刷成当天）。
            # 那种日子是终点不是起点，拿来当网申开始日会把「已结束」写成「刚开放」。
            whole_batch_same_day = n == len(items)
            if n >= 3 and n / len(items) >= 0.4 and not (whole_batch_same_day and day == apply_end):
                apply_start = day
        # 兜底：起点晚于终点一定是某一侧读错了（平台把上架日刷成关窗日之类）。
        # 日历里出现「起 > 止」是最刺眼的自相矛盾，宁可丢掉起点也不留着。
        if apply_start and apply_end and apply_start > apply_end:
            apply_start = None
        out.append({
            "id": f"auto:{sid}:{ptype}:{year or 'na'}",
            "origin": "auto", "group_name": _group_of(company, matched), "company": company, "product": None,
            "grad_year": year, "project_type": ptype,
            "tracks": [{"direction": d, "roles": [s for s, _ in roles[d].most_common(5)], "examples": examples[d]}
                       for d, _ in per_dir.most_common()],
            "apply_start": apply_start, "apply_end": apply_end,
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


def export_job_evidence(jobs_conn, out_path: Path, *, ts: str) -> int:
    """把职位表里的**结构化字段**汇总成每家一条，给日历生成当证据源。

    导出的东西只有接口真给的字段，不做任何推断：
      - cities_by_type  : 按 recruit_type 分组的在招城市（大易 workPlaceStr 的产物）
      - ends_by_type    : 按 recruit_type 分组的真实截止日（大易 endDate，已剔除 3000-01-01 哨兵）
      - starts_by_type  : 批量发布日（同类型里多数职位同一天上架才算，见下方注释）
      - closed_by_type  : 已下架职位的截止日——「这批关窗了」最硬的证据
      - grad_years      : 职位标题里明确写了的届次
      - tracks          : 方向 + 岗位名（已有分类体系）
    在招与已下架**分开统计**：城市/方向只取在招的（下架岗位的城市不代表现在还能投的地方），
    截止日两边的都收（已下架岗位的截止日正是那个批次的关窗日）。
    """
    rows = jobs_conn.execute(
        "SELECT c.name AS company, j.recruit_type, j.cities, j.apply_end, j.publish_at, "
        "j.grad_year, j.title, j.category, j.subcategory, j.closed_at FROM job j "
        "JOIN company c ON c.id = j.company_id"
    ).fetchall()
    per: dict[str, dict] = {}
    for r in rows:
        company = r["company"]
        if not company:
            continue
        d = per.setdefault(company, {"company": company,
                                     "cities_by_type": defaultdict(list),
                                     "ends_by_type": defaultdict(list),
                                     "_end_days": Counter(),
                                     "closed_by_type": defaultdict(list),
                                     "grad_years": Counter(),
                                     "tracks": defaultdict(list),
                                     "_titles": defaultdict(list),
                                     "_publish_days": Counter(),
                                     "_city_count": Counter()})
        rtype = r["recruit_type"] or "campus"
        # 已下架：只贡献截止日，不贡献城市/方向/届次。
        # 一个岗位下架了，它的城市和岗位名不代表「现在还能投什么」，
        # 但它的截止日恰恰证明了那个批次什么时候关的窗。
        if r["closed_at"]:
            if r["apply_end"] and r["apply_end"] not in d["closed_by_type"][rtype]:
                d["closed_by_type"][rtype].append(r["apply_end"])
            continue
        try:
            cities = json.loads(r["cities"] or "[]")
        except (TypeError, ValueError):
            cities = []
        for c in cities if isinstance(cities, list) else []:
            if c and isinstance(c, str) and c not in d["cities_by_type"][rtype]:
                d["cities_by_type"][rtype].append(c)
                d["_city_count"][c] += 1
        # 截止日：按「日期 → 那天有多少条职位截止」累计票数，**不要**只留前 3 个不同日期。
        # 2026-10-26 实测赛诺菲：social 有 86 个不同截止日，最早 3 个是 10-27/10-28/10-29
        # （各几条岗位的零散截止），而真正的「批次收口」是 11-30（117 条）。
        # 取 sorted()[:3] 会把最重要的那天挤掉，日历上就会显示一个毫无代表性的日期。
        if r["apply_end"]:
            d["_end_days"][(rtype, r["apply_end"])] += 1
        if r["publish_at"]:
            # 发布日**不是**网申起点。平台给的 publish_at 是「这条职位上架日」，
            # 有人今天补录一个岗位，今天就成了「网申起点」——拿单条上架日当日历起点是错的。
            # 只有「同类型里明显多数职位同一天上架」才说明那天真的是一批的开放日（校招批量发布）。
            # 判据写在这里而不是下游：下游看到的是已经去重排序的列表，数不出票数了。
            d["_publish_days"][(rtype, r["publish_at"])] += 1
        if r["grad_year"]:
            d["grad_years"][int(r["grad_year"])] += 1
        # 方向用 category/subcategory（已有分类体系），没有分类的职位不硬挂方向
        direction = r["subcategory"] or r["category"]
        if direction and r["title"]:
            d["tracks"][direction].append(r["title"])
        # 原始岗位名（按招聘类型分组，跨方向），给日历「这家在招什么」用
        if r["title"] and rtype:
            d["_titles"][rtype].append(r["title"])

    out = []
    for company, d in per.items():
        cities_all = [c for c, _ in d["_city_count"].most_common(10)]
        # 只保留「同类里 ≥3 条且占该类型 ≥40%」的上架日作为可信起点票。
        # 判据要能挡住「一天补录一条」的噪音，又不能把真正的批量发布挡掉。
        type_total = Counter()
        for (rtype, _day), n in d["_publish_days"].items():
            type_total[rtype] += n
        starts: dict[str, list[str]] = {}
        for (rtype, day), n in sorted(d["_publish_days"].items()):
            total = type_total[rtype]
            if n >= 3 and n / total >= 0.4:
                starts.setdefault(rtype, []).append(day)
        if (not cities_all and not d["ends_by_type"] and not d["grad_years"]
                and not d["closed_by_type"]):
            continue  # 这家什么结构化线索都没有，写进去只会增加噪音
        out.append({
            "company": company,
            "cities": cities_all,
            "cities_by_type": {k: v[:10] for k, v in d["cities_by_type"].items()},
            # 每类取**票数最高**的 3 个截止日（按日期排序输出），反映「这批窗口什么时候收口」。
            # 与 cities_by_type 同构：都是「按类型分组、组内取 top-N」，空组不会出现。
            # 先在**每类内部**取 top-3，再排序 —— 直接对全局 most_common(3) 过滤会把
            # 只有 2~4 条岗位的 campus 整类挤成空数组（2026-10-26 实测赛诺菲）。
            "ends_by_type": {
                t: sorted(dd for dd, _ in Counter(
                    {dd: n for (tt, dd), n in d["_end_days"].items() if tt == t}).most_common(3))
                for t in {tt for tt, _ in d["_end_days"]}
            },
            "closed_by_type": {k: sorted(v)[:3] for k, v in d["closed_by_type"].items()},
            # 起点只给「批量发布日」，见上方 _publish_days 的注释；没有就不给，宁可留空。
            "starts_by_type": {k: v[-3:] for k, v in starts.items()},
            "grad_years": [y for y, _ in d["grad_years"].most_common(3)],
            "tracks": [{"direction": k, "roles": v[:6]} for k, v in d["tracks"].items()][:6],
            # 校招批次里**真实在招的岗位名**（各取前 8 条）。
            # 为什么要单独给：日历的 `tracks[].roles` 是方向聚合，方向分类粗的公司
            # （海信 1000+ 岗全落在几个大类里）日历上就只剩「技术类」三个字，
            # 用户看不出这家到底在招什么。这里给原始标题，让日历条目能写清具体岗位。
            "titles_by_type": {t: v[:8] for t, v in d["_titles"].items()},
            "as_of": ts[:10],
        })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n",
                        encoding="utf-8")
    return len(out)


def manual_rows(entries: list[ManualEntry], jobs_conn, matched: dict[str, list[str]],
                *, data_companies: set[str] | None = None) -> list[dict]:
    out = []
    for e in entries:
        data_cos = matched.get(e.group, [])
        if not data_cos and data_companies:
            # target 清单里没有这家 -> 用人工条目自己的公司名兜底匹配（见 match_entry_company）
            data_cos = match_entry_company(e, data_companies)
        if e.company:
            narrowed = [c for c in data_cos if _matches(e.company, c)]
            data_cos = narrowed or data_cos
        rtype = recruit_type_of_project(e.project_type)
        n = _open_count(jobs_conn, data_cos, rtype) if data_cos else 0
        # 「关联到数据源」和「当前有在招岗位」是两件事，必须分开（2026-10-26 修）：
        # 原来 `jd_company` 只在 n>0 时才写，导致「阿道夫 校招」这种人工资讯明明能对上数据层
        # （该公司有 2 条社招岗位），却因为"校招岗位数为 0"而把公司名也一起丢掉，
        # 后续所有补全（城市/届次/JD）全部失效。关联关系本身与岗位数量无关。
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
            "jd_company": "、".join(data_cos) if data_cos else None, "open_jobs": n if linked else None,
            "notes": e.notes,
        })
    return out


COLS = ["id", "origin", "group_name", "company", "product", "grad_year", "project_type", "tracks",
        "apply_start", "apply_end", "observed_from", "observed_to", "cities", "apply_url", "source_type",
        "source_name", "source_url", "source_date", "as_of", "jd_status", "jd_url", "jd_company", "open_jobs",
        "notes"]


# 自动条目可以「补」给人工条目的字段：只补**空着**的，绝不覆盖人工已写的值。
# 为什么需要补（2026-10-26 实测）：蔚来/小鹏/华为的人工入口条目只有「投递入口」一项，
# `cities`、`apply_end`、`grad_year` 全空；而同一家公司的自动条目从结构化职位表里有
# 429 个岗位的城市与截止日。原来的 dedupe 直接把自动条目丢掉，用户看到的蔚来就只有
# 一行「校招｜城市未知｜无网申时间」——明明数据在手，却在产品里看不见。
#
# 来源字段要跟着「数据从哪来」一起换：城市的证据来自职位表（observed_from/to），
# 若只补 cities 而 source_* 仍写着「官网入口页」，就是在日历里**错标证据来源**——
# 用户按来源去核实时会看到入口页上根本没有城市信息。所以把整个证据四件套一起搬。
_MERGE_FIELDS = ("apply_start", "apply_end", "cities", "grad_year", "tracks",
                 "observed_from", "observed_to", "source_type", "source_name", "source_url", "jd_status", "jd_url")

# 真正承载「内容」的字段。证据字段（observed_*/source_*/jd_*）是一组整体：只有当某条自动条目
# 至少贡献了一个内容字段时，才把它的证据一起搬过去；否则人工条目凭官网公告写下的日期，
# 会被一条只是"顺手补了 jd_url"的自动条目改写成"来自职位列表"，反而失真。
_CONTENT_FIELDS = ("apply_start", "apply_end", "cities", "grad_year", "tracks")


def dedupe_auto(rows: list[dict]) -> list[dict]:
    """人工条目已经覆盖的批次，自动条目不再重复出现；但**先把自动条目的独有字段补进人工条目**。

    为什么需要这一步（2026-10-26 实测）：同一家公司在日历里有两条「校招」——
    一条人工（来源是官网/简章），一条自动（从职位表汇总）。用户看到的是**同一个批次出现两次**，
    且 11 组条目的截止日互相矛盾（人工写 10-31、自动写空或另一个日期），
    回答「360 集团校招什么时候截止」时会出现自相矛盾的两个答案。

    取舍规则（不是"谁更新用谁"，而是按可信度）：
      - **字段级**：人工条目为空的字段，用自动条目补（城市、网申窗口、届次、方向）；
        人工条目已有值的字段一律不动——人工值来自官方公告原文，权威性更高。
      - **条目级**：同 (集团, 批次, 届次) 或 (集团, 批次, 无届次) 已被人工覆盖时，
        合并后丢掉自动条目，日历里只剩一条。
      - 只有自动条目带届次、人工不带（或反之）时**都保留**：那可能是不同届的两个批次，
        合并会把两届混成一条，比重复更糟。

    纯函数、不碰数据库：排序稳定，便于测试。
    """
    manual_keys: set[tuple] = set()
    manual_keys_nograd: set[tuple] = set()
    manual_by_key: dict[tuple, dict] = {}
    for r in rows:
        if r.get("origin") != "manual":
            continue
        key = (r.get("group_name") or r.get("company"), r.get("project_type"))
        manual_keys.add((*key, r.get("grad_year")))
        manual_keys_nograd.add(key)
        manual_by_key.setdefault((*key, r.get("grad_year")), r)
        manual_by_key.setdefault((*key, None), r)
    out, dropped, merged = [], 0, 0
    for r in rows:
        if r.get("origin") == "auto":
            key = (r.get("group_name") or r.get("company"), r.get("project_type"))
            hit = manual_by_key.get((*key, r.get("grad_year")))
            if hit is None and not r.get("grad_year"):
                hit = manual_by_key.get((*key, None))
            if hit is not None:
                borrowed = 0
                for f in _MERGE_FIELDS:
                    if f not in hit or hit.get(f) or not r.get(f):
                        continue
                    hit[f] = r[f]
                    merged += 1
                    if f in _CONTENT_FIELDS:
                        borrowed += 1
                if borrowed:
                    # 内容来自自动条目 → 证据整体改标到自动来源，四件套必须同源
                    for f in ("source_type", "source_name", "source_url",
                              "observed_from", "observed_to", "jd_status", "jd_url"):
                        if r.get(f):
                            hit[f] = r[f]
                dropped += 1
                continue
        out.append(r)
    if dropped:
        # 数量不大，但每条都影响「用户能不能看到城市/截止日」，所以留可观测痕迹：
        # 排查「某家的城市怎么没了」「这条批次怎么少了一半信息」时能直接看到原因。
        import logging

        logging.getLogger(__name__).info(
            "去重：%d 条自动条目并入人工条目（互补填充 %d 个字段后丢弃）", dropped, merged)
    return out


def fill_from_data_layer(rows: list[dict], jobs_conn, *, as_of: str) -> int:
    """人工条目缺 `grad_year`/`cities` 时，从该公司**同招聘类型**的在招岗位里补。

    为什么单独做一步（2026-10-26 实测覆盖率）：日历 1,474 条里 `grad_year` 只有 44.5%、
    `cities` 只有 46.9%；而数据层有 37,312 条校招 + 10,444 条实习岗位，其中 34,866 条带城市、
    14,935 条带届次。这些信息在同一个库里，产品里却看不到——典型的「数据在手、日历没填」。

    `dedupe_auto` 只能补「已经存在一条同 group+batch 的自动条目」的情况；对于有数据源、
    但自动条目被按 (source, 批次, 届次) 拆成好几个分组（所以对不上 key）的公司，它补不到。
    这一步绕开分组，直接用「公司 + 招聘类型」的**岗位级**统计。

    口径（保守，宁缺勿滥）：
      - `grad_year`：该公司同类型岗位里**占比 ≥60% 且至少 3 条**的届次才算；含糊就不填。
      - `cities`：该公司同类型岗位里出现 ≥2 次的 TOP10 城市。只出现 1 次的多半是个别岗位，
        拿它当公司级城市会误导（"这家只在上海招"）。
      - `apply_start`/`apply_end` **不在这里补**：它们需要按批次分组算窗口，
        混在一起算出来的不是任何一次校招的窗口（口径见 auto_entries 的注释）。
      - 只补空字段，绝不覆盖人工值；补了就把证据四件套改标到数据层（`dedupe_auto` 同一规则）。

    返回实际补到的字段数。
    """
    from collections import Counter

    filled = 0
    for r in rows:
        if r.get("origin") != "manual" or (r.get("grad_year") and r.get("cities")):
            continue
        names = [c for c in (r.get("jd_company") or "").split("、") if c]
        if not names:
            continue
        rtype = recruit_type_of_project(r.get("project_type") or "")
        if not rtype:
            continue
        sql = (f"SELECT j.grad_year, j.cities FROM job j JOIN company c ON c.id=j.company_id "
               f"WHERE j.closed_at IS NULL AND j.recruit_type=? AND c.name IN ({','.join('?' * len(names))})")
        got = jobs_conn.execute(sql, [rtype, *names]).fetchall()
        if not got:
            continue
        borrowed = 0
        if not r.get("grad_year"):
            years = Counter(g["grad_year"] for g in got if g["grad_year"])
            if years:
                year, n = years.most_common(1)[0]
                if n >= 3 and n / len(got) >= 0.6:
                    r["grad_year"] = year
                    borrowed += 1
        if not r.get("cities"):
            cities = Counter(c for g in got for c in json.loads(g["cities"] or "[]"))
            picked = [c for c, n in cities.most_common(10) if n >= 2]
            if picked:
                r["cities"] = picked
                borrowed += 1
        if borrowed:
            filled += borrowed
            # 值来自职位表 → 证据必须跟着改，否则日历里会出现「来源：官网简章，城市：深圳」
            # 而简章页上根本没写城市（用户按来源核实会当场发现不一致）。
            r["source_type"] = "data_layer"
            r["source_name"] = f"数据层自动生成（{rtype}）"
            r["source_url"] = r.get("source_url") or r.get("apply_url")
            r["source_date"] = as_of[:10]
    return filled


def build(cal_conn, jobs_conn, *, manual: list[ManualEntry], sources: list[SourceConfig], targets: dict,
          ts: str) -> dict:
    """重建 entry 与 target 表（link_check 保留，用于跨天判断链接连续失败）。"""
    as_of = jobs_conn.execute("SELECT MAX(ts) FROM source_run WHERE status='ok'").fetchone()[0] or ts
    companies = {r[0] for r in jobs_conn.execute(
        "SELECT DISTINCT c.name FROM job j JOIN company c ON c.id=j.company_id WHERE j.closed_at IS NULL")}
    matched = match_targets(targets, companies)
    rows = dedupe_auto(manual_rows(manual, jobs_conn, matched, data_companies=companies)
                       + auto_entries(jobs_conn, sources, targets, as_of=as_of))
    # 补全放在 dedupe 之后：先用自动条目按批次精确补，剩下的零散人工条目再从岗位级统计补，
    # 两步顺序反了会把"按批次算出来的准确值"覆盖成"公司级多数值"。
    filled = fill_from_data_layer(rows, jobs_conn, as_of=as_of)
    if filled:
        import logging

        logging.getLogger(__name__).info("数据层补全：人工条目补到 %d 个字段", filled)
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


def check_links(cal_conn, client: httpx.Client, *, ts: str, sleep=time.sleep, min_interval: float = 1.0,
                workers: int = 8) -> dict:
    """对全部投递/JD/来源链接各发一次 GET（同一主机间隔 ≥1s，遵守各主机 robots.txt）。

    404/410 记为 dead，网络错误/其他状态记为 error；robots 禁止的链接不访问（计入 skipped_robots）。

    主机之间并行（2026-10-23）：串行时 1000 条链接光排队就要十几分钟，再叠加国内站点连不上的
    20 秒超时，daily 的日历步骤 30 分钟直接超时、发布里一直是旧的 calendar.db。现在按主机分桶、
    桶内仍保持 1 rps，桶间并行；同一主机首次就连接失败时，剩余链接直接记 error，不再逐个等超时。
    """
    urls = sorted({u for (u,) in cal_conn.execute(
        """SELECT apply_url FROM entry UNION SELECT jd_url FROM entry UNION
           SELECT source_url FROM entry WHERE origin='manual'""") if u})
    by_host: dict[str, list[str]] = {}
    for url in urls:
        by_host.setdefault(_host(url), []).append(url)
    lock = threading.Lock()
    skipped = [0]

    def one_host(host_urls: list[str]) -> list[tuple[str, str, int | None]]:
        rp = _robots(client, host_urls[0])
        allowed = [u for u in host_urls if rp is None or rp.can_fetch(USER_AGENT, u)]
        with lock:
            skipped[0] += len(host_urls) - len(allowed)
        out: list[tuple[str, str, int | None]] = []
        for i, url in enumerate(allowed):
            if i:
                sleep(min_interval)
            try:
                # 只看状态码，不下载正文（避免大文件或慢速流把探活拖住）
                with client.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": _ACCEPT},
                                   follow_redirects=True) as r:
                    code = r.status_code
                status = "ok" if code < 400 else ("dead" if code in _DEAD else "error")
            except (httpx.ConnectError, httpx.ConnectTimeout):
                # 整个主机连不上：剩下的不再逐个等超时
                out.append((url, "error", None))
                out.extend((u, "error", None) for u in allowed[i + 1:])
                return out
            except httpx.HTTPError:
                code, status = None, "error"
            out.append((url, status, code))
        return out

    results: list[tuple[str, str, int | None]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for chunk in pool.map(one_host, list(by_host.values())):
            results.extend(chunk)

    counts = Counter()
    if skipped[0]:
        counts["skipped_robots"] = skipped[0]
    for url, status, code in results:
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

