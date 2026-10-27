"""Workday 租户（公开 CXS JSON）。外资公司在华招聘常用。侦察：docs/recon/workday.md

列表：POST https://{host}/wday/cxs/{tenant}/{site}/jobs
      body {"appliedFacets": {...}, "limit": 20, "offset": 0, "searchText": ""}
      -> {"total": 244, "jobPostings": [{title, externalPath, locationsText, postedOn, bulletFields}], "facets": [...]}
详情：GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}
      -> {"jobPostingInfo": {title, jobDescription(HTML), location, externalUrl, jobPostingId, ...}}

站点是全球站，本项目只收中国岗位：先用 facets 找到 `locations` 里 descriptor 以
`"{country}, "` 开头的分面 id（如 "China, Shanghai"），再带 `appliedFacets={"locations": ids}` 过滤。
找不到该国家的分面时**不抓**（避免把全球岗位灌进中国数据集），并在抓取记录里显式失败。

source.params:
  host: 如 nvidia.wd5.myworkdayjobs.com
  tenant: 如 nvidia
  site: 站点名，如 NVIDIAExternalCareerSite
  country: 只收该国家的岗位，默认 China
  page_size: 每页条数（Workday 上限 20），默认 20
"""

import re
from collections.abc import Iterator
from datetime import datetime

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import _CST, city_from_english, date_only

LIST_URL = "https://{host}/wday/cxs/{tenant}/{site}/jobs"
DETAIL_URL = "https://{host}/wday/cxs/{tenant}/{site}{path}"
TAG = re.compile(r"<[^>]+>")
BR = re.compile(r"<br\s*/?>|</p>|</li>", re.I)
# 标题里明写的实习/校招（\b 避免 "Internal Tools" 之类误判）
TITLE_INTERN = re.compile(r"\b(?:intern|internship)\b", re.I)
TITLE_CAMPUS = re.compile(r"\b(?:new college graduate|university graduate)\b", re.I)


def _text(html: str | None) -> str | None:
    if not html:
        return None
    text = BR.sub("\n", html)
    text = _unescape(TAG.sub("", text))
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln) or None


def _unescape(s: str) -> str:
    from html import unescape

    return unescape(s)


def _facet_values(facets, parameter: str) -> list[dict]:
    """facets 是嵌套 list（locationMainGroup 里套 locations）；按 facetParameter 找值列表。"""
    out: list[dict] = []

    def walk(items):
        for f in items or []:
            if not isinstance(f, dict):
                continue
            if f.get("facetParameter") == parameter and isinstance(f.get("values"), list):
                out.extend(v for v in f["values"] if isinstance(v, dict))
            walk(f.get("values"))

    walk(facets)
    return out


def country_locations(facets, country: str, facet: str = "locations", prefix_match: bool = True) -> list[str]:
    """属于该国家的 location 分面 id。

    不同租户的分面名不一样，2026-10-26 一天之内见到了三种：
      - `locations`，descriptor 形如 "China, Shanghai"（多数）
      - `locationMainGroup`，国家包在 children 里（Intel：`PRC, Shanghai`）
      - **嵌套在别的分面下面**：惠普/史赛克/3M 的 facets 只有 6 个，China 值挂在
        `Location_Country` / `LocationCountry` 这个分面自己的 values 上，而不是 `locations`。
    所以不能只认一个名字：按「分面参数名含 location」+ 值里有与该国家匹配的 descriptor 来找。
    """
    values = _facet_values(facets, facet)
    if prefix_match:
        # "China, Shanghai" / "China - Shanghai - Shanghai" / "China" 都要认
        pat = re.compile(rf"^{re.escape(country)}\b")
        ok = lambda d: isinstance(d, str) and bool(pat.match(d.strip()))    # noqa: E731
    else:
        ok = lambda d: isinstance(d, str) and d.strip() == country          # noqa: E731

    def pick(vs):
        return [v["id"] for v in vs if ok(v.get("descriptor"))]

    # **顺序不能反**：`locationMainGroup` 里的值叫 "Primary Location" / "Asia Pacific"，
    # 永远匹配不上国家名。先试它会把 `locations` 和 `Location_Country` 一起挡掉
    # （2026-10-26 实测：惠普 0 命中、史赛克同类）。
    ids = pick(values)
    if ids:
        return ids
    ids = pick(_values_of_location_facets(facets))
    if ids:
        return ids
    return pick(_descendants_under(facets, 'locationMainGroup'))


def _values_of_location_facets(facets) -> list[dict]:
    """所有参数名里带 location 的分面下的取值（含一层 children）。

    北美的 Workday 站点把国家做成独立分面 `Location_Country`，值直接挂在分面下；
    而 `_facet_values("locations")` 只找名字正好叫 locations 的那一个，会漏。
    """
    out: list[dict] = []

    def collect(vs):
        for v in vs or []:
            if not isinstance(v, dict):
                continue
            if v.get("id"):
                out.append(v)
            collect(v.get("values"))

    def walk(items):
        for f in items or []:
            if not isinstance(f, dict):
                continue
            param = str(f.get("facetParameter") or f.get("descriptor") or "")
            if "location" in param.lower():
                collect(f.get("values"))
                continue
            walk(f.get("values"))

    walk(facets)
    return out


def _descendants_under(facets, parameter: str) -> list[dict]:
    """取某个分面（如 locationMainGroup）下所有层的取值（含 children），用于分面结构不同的租户。"""
    out: list[dict] = []

    def walk(items):
        for f in items or []:
            if not isinstance(f, dict):
                continue
            if f.get("facetParameter") == parameter:
                def collect(vs):
                    for v in vs or []:
                        if not isinstance(v, dict):
                            continue
                        if v.get("id"):
                            out.append(v)
                        collect(v.get("values"))
                collect(f.get("values"))
                return
            walk(f.get("values"))

    walk(facets)
    return out


# 「2 Locations」「3 locations」——多地点岗位的占位文案，本身不含任何地名。
MULTI_LOC_RE = re.compile(r"^\d+\s+locations?$", re.I)


def _in_country(locations_text: str, country: str, *, keep_unknown: bool = False) -> bool:
    """searchText 兜底源的本地国家校验。

    `locationsText` 是 Workday 的英文地点串（"Pudong, Shanghai" / "2 Locations" /
    "AP-PH-Mandaluyong"）。中间那类「N Locations」不含地名，默认一律不放行——宁可少收，
    也不要把「多地点」当成中国岗位。其余串只要解析出任意一个中国城市就算命中。

    但**不能只做子串匹配**：`"USA - China Lake, CA"` 是加州的中国湖（海军航空站），
    含 "China" 却不是中国岗位（2026-10-26 实测波音 3 条命中里就有这个坑）。
    判据改成「按分隔符切段后，**某一段整体等于**国家名/中国简称」。

    `keep_unknown=True`：`N Locations` 这种**没说地点**的条目放行，交给调用方拿详情页的
    `location` / `additionalLocations` 再判一次。英特尔 2026-10-27 实测：整个站点没有
    国家分面，只能 searchText=China 兜底，34 条里 16 条的 locationsText 是
    「2 Locations」/「3 Locations」，全被这里丢掉 → 入库只剩 18 条；而详情页里
    `location` 明写 `Shanghai, China`。丢弃「没说」和丢弃「明确在外国」是两件事。
    """
    if not locations_text or not country:
        return False
    if cities_of(locations_text):
        return True
    if keep_unknown and MULTI_LOC_RE.match(locations_text.strip()):
        return True
    want = country.strip().lower()
    for part in re.split(r"[,，/|\-]", locations_text):
        p = part.strip().lower()
        if not p:
            continue
        # "China - Shanghai" 的第一段、"[CHN] Beijing" 的 CHN、"(CN)" 的 CN
        p = p.strip("[](){} 　")
        if p == want or (want == "china" and p in {"cn", "chn", "中国", "prc"}):
            return True
    return False


def _detail_locations(detail: dict) -> str:
    """详情页的 `location` + `additionalLocations` 拼成一串，交给 `_in_country` 判国家。"""
    parts = [str(detail.get("location") or "")]
    extra = detail.get("additionalLocations") or []
    if isinstance(extra, list):
        parts += [str(x) for x in extra if x]
    return " / ".join(p for p in parts if p)


# 详情页的 `alpha2Code`（CN / VN / US…）→ 我们关心的国家。只做中国：其余一律判否。
CN_ALPHA2 = {"CN", "CHN", "HKG", "MAC", "TWN"}


def _detail_in_country(detail: dict, country: str) -> bool:
    """详情页国家校验：`country` / `jobRequisitionLocation.country` 优先，再退回地点串解析。

    英特尔 2026-10-27 实测：多地点岗位 `location="PRC, Shanghai"`、
    `additionalLocations=["PRC, Shenzhen","PRC, Beijing"]`、
    `country={"descriptor":"China"}`、`jobRequisitionLocation.country.alpha2Code="CN"`。
    这些结构化字段比任何字符串解析都可靠，有就先用。
    """
    want_cn = country.strip().lower() in {"china", "prc", "cn", "chn", "中国"}
    if want_cn:
        nodes = [detail.get("country")]
        jrl = detail.get("jobRequisitionLocation")
        if isinstance(jrl, dict):
            nodes.append(jrl.get("country"))
        for node in nodes:
            if not isinstance(node, dict):
                continue
            alpha = str(node.get("alpha2Code") or "").strip().upper()
            if alpha:
                # 有 alpha2 就以它为唯一判据（VN/US 直接判否，不再看地点串）
                return alpha in CN_ALPHA2
            desc = str(node.get("descriptor") or "").strip().lower()
            if desc:
                return desc in {"china", "prc", "中国", "cn", "chn"}
    return _in_country(_detail_locations(detail), country)


def _row_known_foreign(locations_text: str) -> bool:
    """列表页地点是「N Locations」这种没说地点的占位文案。"""
    return bool(MULTI_LOC_RE.match((locations_text or "").strip()))


def _posted_on(text) -> str | None:
    """Workday 列表的 postedOn 是相对文案（"Posted Today" / "Posted 3 Days Ago"）。

    只有 "Posted Today" 能确定到"今天"，其余解析不出绝对日期就返回 None——
    按 as_of 反推只会把"30 天前"算成一个看似精确的假日期。
    """
    if not isinstance(text, str):
        return None
    if text.strip().lower() in {"posted today", "today"}:
        return date_only(datetime.now(_CST).date().isoformat())
    return None


def cities_of_many(*locations) -> list[str]:
    """多地点岗位：Workday 详情里有 `location` + `additionalLocations` 列表。

    `locationsText` 形如 "3 Locations"，不要当城市用；只有具体地点串才解析。
    """
    out: list[str] = []
    for loc in locations:
        if isinstance(loc, list):
            for item in loc:
                for c in cities_of(str(item) if item else None):
                    if c not in out:
                        out.append(c)
            continue
        if not loc or "Location" in str(loc):
            continue
        for c in cities_of(str(loc)):
            if c not in out:
                out.append(c)
    return out


REMOTE_WORDS = ("remote", "home office", "work from home", "wfh", "远程", "居家")


def _is_remote(location: str) -> bool:
    """地点串里写的是「远程」而不是城市。"""
    low = location.lower()
    return any(w in low for w in REMOTE_WORDS)


def cities_of(location: str | None) -> list[str]:
    r"""Workday 的地点串形如 `Dalian-Liaoning-China`（连字符，**没有空格**）。

    原来只按 `\s+-\s+|,` 切，遇到 `Dalian-Liaoning-China` 整串丢给 `city_from_english`，
    一个都匹配不上——江森自控 63 条 `Shanghai-Shanghai-China` / `Dalian-Liaoning-China`
    城市 100% 丢失就是这个原因（2026-10-26 实测）。切分符补上裸 `-`（顺带 ` / `），
    并在整串解析失败时逐个 token 试一次。
    """
    if not location:
        return []
    parts = [p for p in re.split(r"\s+-\s+|[,/]|(?<=\w)-(?=\w)", location) if p and p.strip()]
    out: list[str] = []
    for part in parts:
        name = city_from_english(part.strip())
        if name and name not in out:
            out.append(name)
    if not out and _is_remote(location):
        # `China---Remote` / `Remote - China`：远程/居家岗位，地点就是「远程」。
        # 留空会让用户搜「远程」搜不到，而它确实是官方写明的远程岗（雅培 42 条）。
        out.append("远程")
    if not out:
        # 「Macau SAR」「Hong Kong SAR」这类带后缀的整体解析失败，去掉括号/后缀再试
        cleaned = re.sub(r"\([^)]*\)|\bSAR\b", " ", location).strip()
        if cleaned and cleaned != location.strip():
            for part in re.split(r"\s+-\s+|[,/]|(?<=\w)-(?=\w)", cleaned):
                name = city_from_english(part.strip())
                if name and name not in out:
                    out.append(name)
    return out


def recruit_type_of(title: str, default: str) -> str:
    """标题里明写的实习/校招优先；否则用源配置的类型（外资站多数是社招）。"""
    if TITLE_INTERN.search(title):
        return "intern"
    if TITLE_CAMPUS.search(title):
        return "campus"
    return default


@register
class WorkdayAdapter(Adapter):
    id = "workday"

    def _base(self, path: str = "") -> str:
        p = self.source.params
        tpl = DETAIL_URL if path else LIST_URL
        return tpl.format(host=p["host"], tenant=p["tenant"], site=p["site"], path=path)

    def fetch_raw(self) -> Iterator[dict]:
        p = self.source.params
        limit = int(p.get("page_size", 20))
        country = p.get("country", "China")
        # search_text：部分租户（杜邦 wd5/Jobs）的 facets 里根本没有国家维度，
        # 只有 jobFamilyGroup/workerSubType/timeType/locationMainGroup，无法用分面筛国家。
        # 这类租户只能退回服务端关键词检索（Workday 的 searchText 会命中标题/地点/描述）。
        # 依然要求 appliedFacets 为空 + 结果再按地点做一次本地校验，避免把全球岗位收进来。
        search = str(p.get("search_text") or "")
        if search:
            yield from self._paged({}, limit, search, local_country=country)
            return
        # 1) 先拿一次 facets，确定该国家的分面 id
        probe = self.request_json("POST", self._base(),
                                  json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        facet = p.get("location_facet") or "locations"
        exact = bool(p.get("country_exact"))
        ids = country_locations(probe.get("facets"), country, facet=facet, prefix_match=not exact)
        if not ids:
            raise RuntimeError(f"workday {p['tenant']}: 找不到 {country} 的 location 分面，不抓全球岗位"
                               "（若该租户确实没有国家分面，在 params 里配 search_text 走关键词兜底）")
        # **appliedFacets 的 key 必须是分面的真实参数名**，不能写死 "locations"：
        # 惠普/史赛克的国家分面叫 `Location_Country`，传错名字服务端当成未知分面直接忽略，
        # 于是「筛了中国」其实拿到的是全球岗位。优先用配置的 location_facet，
        # 否则从 facets 里反查「哪个分面里装着这个国家」。
        key = facet
        if not probe.get("facets") or not _facet_values(probe.get("facets"), facet):
            key = _facet_containing(probe.get("facets"), ids) or facet
        applied = {key: ids}
        yield from self._paged(applied, limit, "")

    def _paged(self, applied: dict, limit: int, search: str, local_country: str | None = None):
        offset, page, total = 0, 0, None
        while True:
            data = self.request_json("POST", self._base(), json={
                "appliedFacets": applied, "limit": limit, "offset": offset, "searchText": search,
            })
            items = data.get("jobPostings") or []
            if total is None:
                # 只有第一页的 total 可信：Workday 从第二页起返回 total=0（2026-10-22 实测）
                total = data.get("total") or 0
            for item in items:
                # 关键词兜底的源必须本地点名过滤：searchText=China 会命中
                # "APAC Payroll Administrator - China"（地点在菲律宾）这类岗位。
                # 注意 locationsText 是英文城市名（"Pudong, Shanghai"），不会出现 "China"，
                # 所以按 city_from_english 解析出的中文城市反查国家，而不是匹配字面量。
                if local_country and not _in_country(item.get("locationsText") or "", local_country,
                                                     keep_unknown=True):
                    # 明确写着外国地点（越南/印度/马来…）的直接丢，连详情都不用请求。
                    continue
                detail = {}
                try:
                    payload = self.request_json("GET", self._base(item["externalPath"]))
                    detail = payload.get("jobPostingInfo") or {}
                except Exception:  # noqa: BLE001 — 单条详情失败不影响整源，JD 留空
                    detail = {}
                if local_country and _row_known_foreign(item.get("locationsText") or ""):
                    # 列表页是「N Locations」，但详情页把真实地点写出来了（英特尔 2026-10-27：
                    # 34 条 China 检索里 3 条实际在 India/Malaysia）。详情页有 **结构化国家**
                    # 才敢丢；拿不到结构化国家就保留——宁可多留 1 条，不要凭字符串瞎杀。
                    if not _detail_in_country(detail, local_country):
                        continue
                yield {**item, "detail": detail}
            offset += limit
            page += 1
            if not items or len(items) < limit:
                return
            if total and offset >= total:
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return

    def normalize(self, raw: dict) -> Job:
        info = raw.get("detail") or {}
        title = (info.get("title") or raw.get("title") or "").strip()
        path = raw.get("externalPath") or ""
        if not title or not path:
            raise SkipRecord
        p = self.source.params
        url = info.get("externalUrl") or (
            f"https://{p['host']}/en-US/{p['site']}{path}")
        job_id = (info.get("jobPostingId") or info.get("jobReqId")
                  or (raw.get("bulletFields") or [None])[0] or path.rsplit("/", 1)[-1])
        return Job(
            source_id=self.source.id,
            source_job_id=str(job_id),
            company=self.source.company,
            url=url,
            title=title,
            recruit_type=recruit_type_of(title, self.source.recruit_types[0]),
            cities=cities_of_many(info.get("location"), info.get("additionalLocations"),
                                  raw.get("locationsText")),
            degree_min=None,
            # Workday 详情给的是 startDate（真实上架日），列表给的是 postedOn（"Posted Today"/
            # "Posted 30+ Days Ago" 这类相对文案，解析不出日期就不猜）。
            publish_at=date_only(info.get("startDate")) or _posted_on(raw.get("postedOn")),
            description=_text(info.get("jobDescription")),
            requirements=None,
        )


def _facet_containing(facets, ids: list[str]) -> str | None:
    """哪个分面的 values 里装着这些 id（用于反查真实的 `facetParameter`）。"""
    want = set(ids)

    def walk(items):
        for f in items or []:
            if not isinstance(f, dict):
                continue
            for v in f.get("values") or []:
                if isinstance(v, dict) and v.get("id") in want:
                    return f.get("facetParameter")
            got = walk(f.get("values"))
            if got:
                return got
        return None

    return walk(facets)
