"""实习僧（shixiseng）公开聚合站适配器。

定位：**聚合口径的兜底通道**，不是官方直连。凡是能从公司自己门户抓到岗位的公司，
都应该优先用官方适配器（北森/大易/飞书/Workday/自研站），实习僧只在官方入口
拿不到时补位。两个口径在报表里必须分开数（见 scripts/coverage_report.py）。

合规依据（2026-10-29 实测）：
- robots.txt：`https://www.shixiseng.com/robots.txt` 返回 200、0 字节，即没有任何
  Disallow 规则，列表页/详情页都不在禁止范围内。
- 无登录、无验证码、无签名参数；列表页与详情页都是服务端渲染的公开 HTML。
- 只读、限速（默认 1 rps，见 yaml 的 rate_limit_rps），不碰投递/简历接口。

source.params:
  keyword: 搜索关键词，通常就是公司名（必填；缺省用 source.company）
  city: 城市过滤，默认 "全国"
  fetch_detail: 是否逐岗抓详情页拿 JD/截止日，默认 True

数据形态：Nuxt 服务端载荷（`window.__NUXT__=`），用 jobradar.nuxt 解析，
不依赖 node/无头浏览器。

归属校验（**这道闸门不能删**）：实习僧的关键词搜索是模糊匹配，查「宁德时代」
会返回「时代博川」「欢聚时代」的岗位。normalize() 里只有 cname 与目标公司
对得上才入库，否则 SkipRecord——把别家的岗位算到目标公司头上就是造假。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import timedelta

from jobradar.adapters.base import Adapter, CrawlBudgetExceeded, SkipRecord, register
from jobradar.jd_text import template_pollution
from jobradar.models import Job
from jobradar.normalize import date_only, degree_min_from_text, normalize_cities, normalize_degree
from jobradar.nuxt import NuxtParseError, eval_assignments, eval_returning
from jobradar.timeutil import now_ts, parse_ts

BASE = "https://www.shixiseng.com"
LIST_URL = f"{BASE}/interns"
DETAIL_URL = f"{BASE}/intern/{{uuid}}"
DEFAULT_CITY = "全国"
# 实习僧列表固定 20 条/页，服务端不接受 page_size
PAGE_SIZE = 20

# 标题里混着字体图标的私有区码点（如「实习&#xe05d」），不是正文。
# 列表页的实体**不带分号**（实测 `快手-战略分析实习&#xe05d`），详情页带，所以分号可选。
_ICON_ENTITY = re.compile(r"&#x[0-9a-fA-F]{3,6};?|[\ue000-\uf8ff]")
_COMPANY_SUFFIX = re.compile(
    r"(?:股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司)$"
)

DETAIL_KEYS = ("iname", "info", "info_is_html", "city", "cname", "minsal", "maxsal",
               "degree", "endtime", "address", "skills", "month", "day")


def clean_title(text: str | None) -> str:
    """去掉图标码点、压缩空白。"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", _ICON_ENTITY.sub("", text)).strip()


def _same_list_title(listed, verified):
    if not isinstance(listed, str) or not isinstance(verified, str):
        return False
    if clean_title(listed) == verified:
        return True
    # 不还原字体字符；只把未知位置与既有、带观测时间的标题逐字符比较。
    listed = re.sub(r'\s+', ' ', listed).strip()
    parts, start = [], 0
    for match in _ICON_ENTITY.finditer(listed):
        parts.extend((re.escape(listed[start:match.start()]), '.'))
        start = match.end()
    parts.append(re.escape(listed[start:]))
    return bool(re.fullmatch(''.join(parts), verified))


def company_core(name: str | None) -> str:
    """公司名归一：去空白、去法律后缀。"""
    if not name:
        return ""
    s = re.sub(r"[\s\u3000]+", "", str(name))
    return _COMPANY_SUFFIX.sub("", s)


def same_company(a: str | None, b: str | None) -> bool:
    """两个公司名是否指同一家。

    三条规则，从紧到松：
    1. 归一后相等；
    2. 以短名开头（≥2 字）：覆盖「华为」→「华为云计算技术有限公司」这类母品牌前缀，
       但「小米」不会吃掉「达州小米汽车」（不是前缀）；
    3. 两者都 ≥3 字且互为子串：覆盖「快手科技」vs「北京快手科技有限公司」这种带地名前缀。
    2 字名只走规则 1、2，不做任意子串匹配。
    """
    ca, cb = company_core(a), company_core(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    short, long = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if len(short) >= 2 and long.startswith(short):
        return True
    if len(ca) >= 3 and len(cb) >= 3:
        return ca in cb or cb in ca
    return False


def belongs_to_company(observed, target):
    actual, expected = company_core(observed), company_core(target)
    if actual and actual != expected and expected.startswith(actual):
        return False  # 母品牌名称不足以证明岗位归属某一个子公司。
    return same_company(observed, target)


def _html_to_text(fragment: str | None) -> str | None:
    """详情页 JD 是 HTML 片段，落库要纯文本。"""
    if not fragment:
        return None
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    s = re.sub(r"[ \t\u3000]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip() or None


def parse_list_page(html: str) -> tuple[list[dict], int]:
    """列表页 -> (岗位列表, 总数)。岗位是 `data[0].interns.data` 里的对象。"""
    payload = eval_returning(html)
    for block in payload.get("data") or []:
        if not isinstance(block, dict):
            continue
        interns = block.get("interns")
        if not isinstance(interns, dict):
            continue
        jobs = interns.get("data")
        if not isinstance(jobs, list) or any(not isinstance(j, dict) or not j.get("uuid") for j in jobs):
            raise RuntimeError("实习僧列表记录不完整")
        total = interns.get("total")
        if type(total) is not int and not (isinstance(total, str) and total.isascii() and total.isdecimal()):
            raise RuntimeError("实习僧列表总数无效")
        if int(total) < 0:
            raise RuntimeError("实习僧列表总数无效")
        return jobs, int(total)
    raise RuntimeError("实习僧列表结构不完整")


def parse_detail_page(html: str) -> dict:
    """详情页 -> 字段 dict（语句式载荷，只取我们需要的键）。"""
    return eval_assignments(html, keys=DETAIL_KEYS)


def _public_terms(detail: dict) -> str | None:
    """保留详情页公开明示的数值；不解码列表字体混淆，不从缺失值推断不限。"""
    def number(key, maximum):
        value = detail.get(key)
        if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
            return None
        value = int(value)
        return value if 0 < value <= maximum else None

    lines = []
    low, high = number("minsal", 999999), number("maxsal", 999999)
    # 公开详情页显示「180-200/天」；只保存明示区间，不推断币种、税前税后或转正薪资。
    if low is not None and high is not None and low <= high:
        lines.append(f"薪资：{low}-{high}/天")
    if (days := number("day", 7)) is not None:
        lines.append(f"每周出勤：{days}天/周")
    if (months := number("month", 60)) is not None:
        lines.append(f"实习时长：{months}个月")
    return "实习僧详情页标注（具体资格以正文为准）：\n" + "\n".join(lines) if lines else None


@register
class ShixisengAdapter(Adapter):
    id = "shixiseng"

    @property
    def keyword(self) -> str:
        return str(self.source.params.get("keyword") or self.source.company)

    @property
    def city(self) -> str:
        return str(self.source.params.get("city") or DEFAULT_CITY)

    def _list(self, page: int) -> tuple[list[dict], int]:
        html = self.request_text(
            "GET", LIST_URL,
            params={"keyword": self.keyword, "city": self.city, "type": "intern", "page": page},
            headers={"Referer": BASE + "/"},
        )
        try:
            return parse_list_page(html)
        except NuxtParseError as e:  # 站点改版或被拦：报错要能看出是哪一步
            raise RuntimeError(f"实习僧列表页解析失败（第 {page} 页）：{e}") from e

    def _detail(self, uuid: str) -> dict:
        html = self.request_text("GET", DETAIL_URL.format(uuid=uuid),
                                 headers={"Referer": BASE + "/"})
        try:
            return parse_detail_page(html)
        except NuxtParseError:
            return {}

    def _cached_detail(self, item, *, allow_old=False):
        hours = self.source.params.get('detail_cache_hours', 0)
        if type(hours) is not int or not 0 < hours <= 168:
            return None
        cached = getattr(self, 'cached_texts', {}).get(str(item.get('uuid')))
        if not cached or not belongs_to_company(item.get('cname'), self.source.company):
            return None
        if not _same_list_title(item.get('name'), cached.get('title')):
            return None
        degree = normalize_degree(str(item.get('degree') or ''))
        if degree and normalize_degree(cached.get('degree_min')) != degree:
            return None
        try:
            cities = json.loads(cached['cities']) if isinstance(cached['cities'], str) else cached['cities']
            listed = normalize_cities(re.split(r'[,，/、]', str(item.get('city') or '')))
            if listed and listed != normalize_cities(cities):
                return None
            observed, current = parse_ts(cached['fetched_at']), parse_ts(now_ts())
            if observed > current or (not allow_old and current - observed > timedelta(hours=hours)):
                return None
        except (ValueError, TypeError, KeyError):
            return None
        body = (cached.get('description'), cached.get('requirements'))
        if not any(body) or any(template_pollution(value) for value in body):
            return None
        end = date_only(item.get('endtime'), floor_year=2024)
        if end and end != cached.get('apply_end'):
            return None
        return {**cached, 'cities': cities}

    def fetch_raw(self) -> Iterator[dict]:
        fetch_detail = bool(self.source.params.get("fetch_detail", True))
        page = 1
        seen = set()
        while True:
            items, total = self._list(page)
            if not items:
                if page != 1 or total != 0:
                    raise RuntimeError('实习僧列表中途为空，未完成采集')
                break
            ids = {str(item['uuid']) for item in items}
            if len(ids) != len(items) or seen.intersection(ids):
                raise RuntimeError('实习僧列表重复分页，未完成采集')
            seen.update(ids)
            for it in items:
                if it.get('cname') and not belongs_to_company(it['cname'], self.source.company):
                    continue
                detail = {}
                cached = self._cached_detail(it) if fetch_detail else None
                if fetch_detail:
                    if not cached:
                        try:
                            detail = self._detail(str(it["uuid"]))
                        except CrawlBudgetExceeded:
                            raise
                        except Exception:  # noqa: BLE001 — 正文失败保留原观测，完整列表仍受分页校验。
                            detail = {}
                        if not detail:
                            cached = self._cached_detail(it, allow_old=True)
                yield {"list": it, "detail": detail, 'cached': cached}
            if page * PAGE_SIZE >= total:
                if len(seen) < total:
                    raise RuntimeError('实习僧列表数量不足，未完成采集')
                break
            if self.source.max_pages and page >= self.source.max_pages:
                break
            page += 1

    def normalize(self, raw: dict) -> Job:
        it, detail = raw["list"], raw.get("detail") or {}
        cached = raw.get('cached') or {}
        uuid = it.get("uuid")
        if not uuid:
            raise SkipRecord
        cname = detail.get("cname") or it.get("cname")
        if not belongs_to_company(cname, self.source.company):
            # 关键词搜出来的别家岗位，不能算到本公司头上
            raise SkipRecord
        title = cached.get('title') if cached else clean_title(detail.get("iname") or it.get("name"))
        if not title:
            raise SkipRecord
        city = str(detail.get("city") or it.get("city") or "").strip()
        cities = cached.get('cities') if cached else [c for c in re.split(r"[,，/、]", city) if c][:3]
        degree = cached.get('degree_min') if cached else detail.get("degree") or it.get("degree")
        info = detail.get("info")
        if detail.get("info_is_html") is not False:
            info = _html_to_text(info)
        return Job(
            source_id=self.source.id,
            source_job_id=str(uuid),
            company=self.source.company,
            url=DETAIL_URL.format(uuid=uuid),
            title=title,
            recruit_type="intern",
            cities=cities,
            degree_min=degree_min_from_text(str(degree)) if degree else None,
            apply_end=cached.get('apply_end') if cached else date_only(detail.get("endtime"), floor_year=2024),
            description=cached.get('description') if cached else info,
            requirements=cached.get('requirements') if cached else _public_terms(detail),
            text_observed_at=cached.get('fetched_at') if cached else None,
        )
