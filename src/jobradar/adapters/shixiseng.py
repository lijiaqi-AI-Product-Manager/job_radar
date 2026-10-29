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

import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import date_only, degree_min_from_text
from jobradar.nuxt import NuxtParseError, eval_assignments, eval_returning

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
        jobs = [j for j in (interns.get("data") or []) if isinstance(j, dict) and j.get("uuid")]
        total = interns.get("total")
        return jobs, int(total) if isinstance(total, int) else len(jobs)
    return [], 0


def parse_detail_page(html: str) -> dict:
    """详情页 -> 字段 dict（语句式载荷，只取我们需要的键）。"""
    return eval_assignments(html, keys=DETAIL_KEYS)


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

    def fetch_raw(self) -> Iterator[dict]:
        fetch_detail = bool(self.source.params.get("fetch_detail", True))
        page = 1
        while True:
            items, total = self._list(page)
            if not items:
                break
            for it in items:
                detail = {}
                if fetch_detail:
                    try:
                        detail = self._detail(str(it["uuid"]))
                    except Exception:  # noqa: BLE001 — 详情失败不该让整源失败，只是缺 JD
                        detail = {}
                yield {"list": it, "detail": detail}
            if page * PAGE_SIZE >= total:
                break
            if self.source.max_pages and page >= self.source.max_pages:
                break
            page += 1

    def normalize(self, raw: dict) -> Job:
        it, detail = raw["list"], raw.get("detail") or {}
        uuid = it.get("uuid")
        if not uuid:
            raise SkipRecord
        cname = detail.get("cname") or it.get("cname")
        if not same_company(cname, self.source.company):
            # 关键词搜出来的别家岗位，不能算到本公司头上
            raise SkipRecord
        title = clean_title(detail.get("iname") or it.get("name"))
        if not title:
            raise SkipRecord
        city = str(detail.get("city") or it.get("city") or "").strip()
        cities = [c for c in re.split(r"[,，/、]", city) if c][:3]
        degree = detail.get("degree") or it.get("degree")
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
            apply_end=date_only(detail.get("endtime"), floor_year=2024),
            description=info,
        )
