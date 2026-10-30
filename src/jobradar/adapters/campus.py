"""高校就业网「招聘信息」适配器（聚合口径 grade C）。

定位：与 shixiseng 同级的**聚合兜底通道**。高校就业网发布的是企业投给学校的
招聘简章/职位信息，页面由学校 CMS 服务端渲染，公开可读、无需登录。

合规依据（2026-10-30 实测）：
- 列表页/详情页均为公开 HTML，无登录、无验证码、无签名参数。
- 只读、限速（默认 1 rps）。
- 只取「招聘信息」栏目（企业主动投递给学校的岗位信息），不碰学生简历/投递接口。

source.params:
  school: 学校键（见 SCHOOLS，目前 "nankai"）
  match:  该企业在就业网上登记的公司全名（字符串或字符串列表）。**必填**。
          就业网同一目标可能对应多个法人（如银行总行+分行），所以允许列表。
  max_pages: 翻多少页列表，默认 3（每页 20 条，覆盖最近约两周）
  list_cache_ttl: 列表页进程内缓存秒数，默认 600；同一所学校的多个源共用缓存，
          否则 34 家各扫 50 页会把学校站点打 1,700 次。设 0 关闭缓存。

归属校验：只有列表里的公司名与 `match` 归一后完全相等才入库。高校就业网的
公司字段是学校审核时录入的全名，一般很规范；不做模糊匹配是刻意的——
「迪卡侬…南开大悦城分公司」这种含地名的子公司会被模糊匹配错认成「大悦城」。
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator

import httpx

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import date_only, degree_min_from_text

# 学校注册表：列表页模板 + 详情页模板
SCHOOLS: dict[str, dict[str, str]] = {
    "nankai": {
        "base": "https://career.nankai.edu.cn",
        "list": "https://career.nankai.edu.cn/correcruit/index/p/{page}.html",
        "detail": "https://career.nankai.edu.cn/correcruit/content/id/{id}.html",
        "list_url": "https://career.nankai.edu.cn/correcruit/index.html",
    },
    "tiangong": {
        "base": "https://jobs.tiangong.edu.cn",
        "list": "https://jobs.tiangong.edu.cn/correcruit/index/p/{page}.html",
        "detail": "https://jobs.tiangong.edu.cn/correcruit/content/id/{id}.html",
        "list_url": "https://jobs.tiangong.edu.cn/correcruit/index.html",
    },
    "hebut": {
        "base": "https://career.hebut.edu.cn",
        "list": "https://career.hebut.edu.cn/correcruit/index/p/{page}.html",
        "detail": "https://career.hebut.edu.cn/correcruit/content/id/{id}.html",
        "list_url": "https://career.hebut.edu.cn/correcruit/index.html",
    },
    "tust": {
        "base": "https://jy.tust.edu.cn",
        "list": "https://jy.tust.edu.cn/correcruit/index/p/{page}.html",
        "detail": "https://jy.tust.edu.cn/correcruit/content/id/{id}.html",
        "list_url": "https://jy.tust.edu.cn/correcruit/index.html",
    },
    "tjcu": {
        "base": "https://career.tjcu.edu.cn",
        "list": "https://career.tjcu.edu.cn/correcruit/index/p/{page}.html",
        "detail": "https://career.tjcu.edu.cn/correcruit/content/id/{id}.html",
        "list_url": "https://career.tjcu.edu.cn/correcruit/index.html",
    },
}

_ITEM = re.compile(
    r'<li>\s*<div class="date">\s*<span class="day">(\d+)</span>\s*<span class="year">([\d.]+)</span>\s*</div>\s*'
    r'<div class="title1"><a href="([^"]+)"[^>]*>(.*?)</a></div>\s*'
    r'<div class="company">\s*<a href="([^"]+)"[^>]*>【(.*?)】</a>(.*?)</div>',
    re.S,
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[\s\u3000]+")
_COMPANY_SUFFIX = re.compile(
    r"(?:股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司)$"
)
_DEGREE_WORDS = ("博士", "硕士", "本科", "大专", "专科", "高中", "中专", "不限")
_SALARY = re.compile(r"\d|面议|元")


def _is_city(seg: str) -> bool:
    """城市段判定：以省/市/区/县结尾，或「XX自治区」「国外/全国」。

    皮肤 C 的「城市 / 类别 / 学历 / 薪资」里，类别段（工程技术人员、其他人员）不带这些后缀，
    单纯用「不是学历、不是薪资」会把它当城市，所以在列表页阶段就要按后缀挡掉。
    """
    s = seg.strip()
    if not s:
        return False
    return s.endswith(("省", "市", "区", "县")) or "自治区" in s or s in {"国外", "全国"}
_ID = re.compile(r"/(\d+)\.html")

# 皮肤 B：<ul class="zpxx"><li><a class="up" href=…>标题</a><a class="down" href=…>公司</a><div class="r">日期</div>
_ZPXX = re.compile(
    r'<li[^>]*>\s*<div class="l">\s*'
    r'<a[^>]*class="up"[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*'
    r'<a[^>]*class="down"[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</div>\s*'
    r'<div class="r">\s*([\d-]*)\s*</div>',
    re.S,
)

# 列表页进程内缓存：同一所学校的多个源共用一次翻页，避免把站点打成 1,700 次请求。
# 皮肤 C：<ul class="zhaopin_ul"><li><div class="zw_title"><a class="lizw" href=…>标题</a>
#        <a class="ligs" href=…>公司</a><p>日期</p></div><div class="zw_cate">城市 / 类别 / 学历 / 薪资</div>
_ZHAOPIN_UL = re.compile(
    r'<li[^>]*>\s*<div class="[^"]*zw_title[^"]*">\s*<div class="[^"]*zw_titleleft[^"]*">\s*'
    r'<a[^>]*class="lizw"[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*'
    r'<a[^>]*class="ligs"[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</div>\s*'
    r'<p>\s*([\d-]*)\s*</p>\s*</div>\s*'
    r'<div class="[^"]*zw_cate[^"]*">\s*(.*?)\s*</div>',
    re.S,
)

# 列表页进程内缓存：同一所学校的多个源共用一次翻页，避免把站点打成上千次请求。
_LIST_CACHE: dict[tuple[str, int], tuple[float, list[dict]]] = {}


def _text(fragment: str | None) -> str:
    """HTML 片段 -> 单行纯文本。"""
    if not fragment:
        return ""
    s = _TAG.sub(" ", fragment)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return _WS.sub(" ", s).strip()


def company_core(name: str | None) -> str:
    """公司名归一：去空白与法律后缀。"""
    if not name:
        return ""
    return _COMPANY_SUFFIX.sub("", _WS.sub("", str(name)))


def same_company(a: str | None, b: str | None) -> bool:
    """仅在归一后完全相等时判定为同一家（本适配器刻意不做模糊匹配）。"""
    ca, cb = company_core(a), company_core(b)
    return bool(ca) and ca == cb


def parse_list_page(html: str, base: str) -> list[dict]:
    """列表页 -> 条目列表。

    这套「correcruit」就业网 CMS 至少有两种皮肤：
    A（南开/天工大）`<li><div class="date">…<div class="title1"><a>…<div class="company">【公司】`
    B（河北工大等）`<ul class="zpxx"><li><a class="up">标题</a><a class="down">公司</a><div class="r">日期`
    先按 A 解析，零条再按 B 解析。
    """
    out = _parse_school_theme(html, base)
    if out:
        return out
    out = _parse_zpxx_theme(html, base)
    if out:
        return out
    return _parse_zhaopin_ul_theme(html, base)


def _parse_school_theme(html: str, base: str) -> list[dict]:
    out: list[dict] = []
    for day, ym, href, title, _chref, company, meta in _ITEM.findall(html):
        parts = [p.strip() for p in _text(meta).split("/") if p.strip()]
        cities = [p for p in parts if not any(w in p for w in _DEGREE_WORDS) and not _SALARY.search(p)]
        degree = next((p for p in parts if any(w in p for w in _DEGREE_WORDS)), "")
        salary = next((p for p in parts if _SALARY.search(p) and p not in cities), "")
        url = href if href.startswith("http") else base + href
        m = _ID.search(url)
        out.append(
            {
                "id": m.group(1) if m else url,
                "url": url,
                "title": _text(title),
                "company": _text(company),
                "cities": cities[:3],
                "degree": degree,
                "salary": salary,
                "date": f"{ym.replace('.', '-')}-{int(day):02d}" if ym else "",
            }
        )
    return out


def _parse_zpxx_theme(html: str, base: str) -> list[dict]:
    out: list[dict] = []
    for href, title, _chref, company, date in _ZPXX.findall(html):
        url = href if href.startswith("http") else base + href
        m = _ID.search(url)
        d = date.strip()
        out.append(
            {
                "id": m.group(1) if m else url,
                "url": url,
                "title": _text(title),
                "company": _text(company),
                "cities": [],
                "degree": "",
                "salary": "",
                "date": d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else "",
            }
        )
    return out


def _parse_zhaopin_ul_theme(html: str, base: str) -> list[dict]:
    out: list[dict] = []
    for href, title, _chref, company, date, cate in _ZHAOPIN_UL.findall(html):
        url = href if href.startswith("http") else base + href
        m = _ID.search(url)
        parts = [p.strip() for p in _text(cate).split("/") if p.strip()]
        # 皮肤 C 的顺序是「城市… / 职位类别 / 学历 / 薪资」，类别段不带省市区县后缀，靠这个剔除
        cities = [p for p in parts if _is_city(p)]
        degree = next((p for p in parts if any(w in p for w in _DEGREE_WORDS)), "")
        salary = next((p for p in parts if _SALARY.search(p) and p not in cities), "")
        d = date.strip()
        out.append(
            {
                "id": m.group(1) if m else url,
                "url": url,
                "title": _text(title),
                "company": _text(company),
                "cities": cities[:3],
                "degree": degree,
                "salary": salary,
                "date": d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else "",
            }
        )
    return out


def _field(text: str, label: str, *, stop: tuple[str, ...], limit: int = 60) -> str | None:
    """抽「标签：值」字段，值到下一个已知标签为止，且不超过 limit 字符。

    早期版本只在「stop 词出现在前 limit 个字符内」时才截断，页面上少一个标签
    （例如没有「浏览量」）就会把后面整段字段都吞进来 —— 2026-10-30 修。
    """
    i = text.find(label)
    if i < 0:
        return None
    rest = text[i + len(label):]
    cut = len(rest)
    for s in stop:
        j = rest.find(s)
        if 0 <= j < cut:
            cut = j
    v = rest[: min(cut, limit)].strip(" 　：:").strip()
    return v or None


def parse_detail_page(html: str) -> dict:
    """详情页 -> 结构化字段 + JD 正文。"""
    text = _text(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I))
    fields = {
        "city": _field(text, "工作地域：", stop=("职位类别", "学历要求", "招聘人数", "发布时间")),
        "category": _field(text, "职位类别：", stop=("学历要求", "招聘人数", "发布时间")),
        "degree": _field(text, "学历要求：", stop=("招聘人数", "发布时间", "浏览量")),
        "headcount": _field(text, "招聘人数：", stop=("发布时间", "浏览量")),
        "publish": _field(text, "发布时间：", stop=("浏览量", "专业要求", "职位描述", "职位投递")),
        "apply_url": _field(
            text, "职位投递网址链接：",
            stop=("工作地域", "职位类别", "学历要求", "招聘人数", "发布时间", "职位描述", "专业要求"),
            limit=200,
        ),
    }
    if not fields["apply_url"]:
        fields["apply_url"] = _field(
            text, "职位投递邮箱：",
            stop=("工作地域", "职位类别", "学历要求", "招聘人数", "发布时间", "职位描述", "专业要求"),
            limit=200,
        )
    if not fields["apply_url"]:
        m = re.search(r"(?:职位投递网址链接|职位投递邮箱)[：:]\s*(https?://[^\s]+)", text)
        fields["apply_url"] = m.group(1) if m else None
    jd_start = text.find("职位描述：")
    if jd_start >= 0:
        jd = text[jd_start + len("职位描述："):]
        fields["description"] = jd.strip() or None
    else:
        fields["description"] = None
    return fields


@register
class CampusAdapter(Adapter):
    id = "campus"

    @property
    def school(self) -> str:
        key = str(self.source.params.get("school") or "")
        if key not in SCHOOLS:
            raise RuntimeError(f"未知的高校键 {key!r}，见 adapters/campus.py 的 SCHOOLS")
        return key

    def _matches(self) -> list[str]:
        raw = self.source.params.get("match")
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, list):
            return [str(x) for x in raw]
        raise RuntimeError(f"source {self.source.id} 缺少 params.match（该企业在就业网上的公司全名）")

    def _cache_ttl(self) -> float:
        try:
            return float(self.source.params.get("list_cache_ttl", 600))
        except (TypeError, ValueError):
            return 600.0

    def _list(self, page: int) -> list[dict]:
        cfg = SCHOOLS[self.school]
        key = (self.school, page)
        ttl = self._cache_ttl()
        now = time.monotonic()
        if ttl > 0:
            hit = _LIST_CACHE.get(key)
            if hit is not None and now - hit[0] < ttl:
                return hit[1]
        url = cfg["list"].format(page=page) if page > 1 else cfg["list_url"]
        try:
            html = self.request_text("GET", url)
        except httpx.HTTPStatusError as exc:
            # 就业网栏目长度各校不同（南开 50 页、天工大 60+ 页），翻到尾部返回 404 属正常结束
            if exc.response.status_code in (404, 410):
                return []
            raise
        items = parse_list_page(html, cfg["base"])
        if ttl > 0:
            _LIST_CACHE[key] = (now, items)
        return items

    def _detail(self, item: dict) -> dict:
        try:
            html = self.request_text("GET", item["url"])
        except Exception:  # noqa: BLE001 — 详情失败只是缺 JD，不该让整源失败
            return {}
        return parse_detail_page(html)

    def fetch_raw(self) -> Iterator[dict]:
        max_pages = int(self.source.max_pages or 3)
        for page in range(1, max_pages + 1):
            items = self._list(page)
            if not items:
                break
            for it in items:
                if not any(same_company(it["company"], m) for m in self._matches()):
                    continue
                yield {"item": it, "detail": self._detail(it)}

    def normalize(self, raw: dict) -> Job:
        it, detail = raw["item"], raw.get("detail") or {}
        if not it.get("title"):
            raise SkipRecord
        cities = it.get("cities") or []
        city_field = detail.get("city")
        if city_field:
            cities = [c for c in re.split(r"[,，/、\s]+", city_field) if c][:3]
        degree = detail.get("degree") or it.get("degree") or ""
        return Job(
            source_id=self.source.id,
            source_job_id=str(it["id"]),
            company=self.source.company,
            url=it["url"],
            title=it["title"],
            recruit_type="campus",
            cities=cities,
            degree_min=degree_min_from_text(degree) if degree else None,
            publish_at=date_only(detail.get("publish") or it.get("date"), floor_year=2024),
            description=detail.get("description"),
        )
