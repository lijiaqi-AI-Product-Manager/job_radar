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

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job

LIST_URL = "https://{host}/wday/cxs/{tenant}/{site}/jobs"
DETAIL_URL = "https://{host}/wday/cxs/{tenant}/{site}{path}"
TAG = re.compile(r"<[^>]+>")
BR = re.compile(r"<br\s*/?>|</p>|</li>", re.I)
# 标题里明写的实习/校招（\b 避免 "Internal Tools" 之类误判）
TITLE_INTERN = re.compile(r"\b(?:intern|internship)\b", re.I)
TITLE_CAMPUS = re.compile(r"\b(?:new college graduate|university graduate)\b", re.I)

# Workday 的 location 是英文（"China, Shanghai"）；数据集里的 cities 用中文
CITY_EN = {
    "beijing": "北京", "shanghai": "上海", "shenzhen": "深圳", "guangzhou": "广州",
    "hangzhou": "杭州", "suzhou": "苏州", "nanjing": "南京", "chengdu": "成都",
    "wuhan": "武汉", "xi'an": "西安", "xian": "西安", "tianjin": "天津",
    "hong kong": "香港", "taipei": "台北", "hsinchu": "新竹", "dalian": "大连",
    "qingdao": "青岛", "xiamen": "厦门", "chongqing": "重庆", "changsha": "长沙",
    "hefei": "合肥", "wuxi": "无锡", "dongguan": "东莞", "zhuhai": "珠海",
    "foshan": "佛山", "shenyang": "沈阳", "kunshan": "昆山",
}


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


def country_locations(facets, country: str) -> list[str]:
    """`locations` 分面中属于该国家的 id（descriptor 形如 "China, Shanghai"）。"""
    prefix = f"{country}, "
    return [v["id"] for v in _facet_values(facets, "locations")
            if isinstance(v.get("descriptor"), str) and v["descriptor"].startswith(prefix)]


def cities_of(location: str | None) -> list[str]:
    if not location:
        return []
    out = []
    for part in location.split(","):
        name = CITY_EN.get(part.strip().lower())
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
        # 1) 先拿一次 facets，确定该国家的分面 id
        probe = self.request_json("POST", self._base(),
                                  json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        ids = country_locations(probe.get("facets"), country)
        if not ids:
            raise RuntimeError(f"workday {p['tenant']}: 找不到 {country} 的 location 分面，不抓全球岗位")
        applied = {"locations": ids}
        offset, page, total = 0, 0, None
        while True:
            data = self.request_json("POST", self._base(), json={
                "appliedFacets": applied, "limit": limit, "offset": offset, "searchText": "",
            })
            items = data.get("jobPostings") or []
            if total is None:
                # 只有第一页的 total 可信：Workday 从第二页起返回 total=0（2026-10-22 实测）
                total = data.get("total") or 0
            for item in items:
                detail = {}
                try:
                    payload = self.request_json("GET", self._base(item["externalPath"]))
                    detail = payload.get("jobPostingInfo") or {}
                except Exception:  # noqa: BLE001 — 单条详情失败不影响整源，JD 留空
                    detail = {}
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
            cities=cities_of(info.get("location") or raw.get("locationsText")),
            degree_min=None,
            description=_text(info.get("jobDescription")),
            requirements=None,
        )
