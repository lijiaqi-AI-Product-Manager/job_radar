"""「云就业」SaaS 高校就业网适配器（id: yunjiuye，聚合口径 grade C）。

定位：与 campus / shixiseng 同级的聚合通道。全国 1,000+ 所高校的就业网跑在同一套
SaaS（bysjy.com.cn / goworkla.cn / yunjiuye.com / jiuye.com）上，每所学校是一个
独立子域，共用公开 JSON 接口：

- 列表 `GET https://<host>/module/getjobs?start=1&count=100[&k=关键词]`
  返回 `{"code":1,"data":[{publish_id, company_name, job_name, city_name,
  publish_time, end_time, salary, degree_require, about_major, is_practice, ...}]}`
- 详情 `GET https://<host>/detail/job?id=<publish_id>`：服务端渲染，含岗位职责/任职要求。

合规依据（2026-10-30 实测）：公开页面与公开 JSON，无登录、无验证码、无签名参数；
与学校就业网对外展示的信息一致。只读，默认 1 rps。

source.params:
  host:   学校子域，如 "cauc.bysjy.com.cn"
  match:  该企业在学校站上登记的公司全名（字符串或列表）。**必填**。
  keyword: 传给接口的关键词，默认取公司名，可加速并降低抓取量。
  max_pages: 翻多少页，默认 5（每页 100 条）
  fetch_detail: 是否抓详情页取 JD，默认 true

归属校验：只有 `company_name` 与 `match` 归一后完全相等才入库（理由同 campus：
模糊匹配会把「XX 分公司」错认成母公司）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

import httpx

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import date_only, degree_min_from_text

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_COMPANY_SUFFIX = re.compile(
    r"(股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司)$"
)


def company_core(name: str | None) -> str:
    if not name:
        return ""
    return _COMPANY_SUFFIX.sub("", _WS.sub("", str(name)))


def same_company(a: str | None, b: str | None) -> bool:
    ca, cb = company_core(a), company_core(b)
    return bool(ca) and ca == cb


def _text(html: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", html)).strip()


@register
class YunjiuyeAdapter(Adapter):
    id = "yunjiuye"
    name = "云就业 SaaS 高校就业网"

    def __init__(self, source, client: httpx.Client, *, sleep=None, **kwargs) -> None:
        if sleep is None:
            super().__init__(source, client)
        else:
            super().__init__(source, client, sleep=sleep)
        self.host = str(self.source.params.get("host") or "")
        if not self.host:
            raise ValueError(f"{self.source.id}: params.host 必填")
        self.base = f"https://{self.host}"
        self.max_pages = int(self.source.params.get("max_pages") or 5)
        # 关键词全部落空时，全量翻页要翻得更深：长尾岗位常落在第 6 页以后。
        self.fallback_pages = int(self.source.params.get("fallback_pages") or max(self.max_pages, 10))
        self.fetch_detail = bool(self.source.params.get("fetch_detail", True))

    def _matches(self) -> list[str]:
        raw = self.source.params.get("match")
        if isinstance(raw, str):
            return [raw]
        return [str(x) for x in (raw or [])]

    def _list(self, keyword: str, pages: int | None = None) -> list[dict]:
        out: list[dict] = []
        for page in range(pages or self.max_pages):
            resp = self.request_text(
                "GET",
                f"{self.base}/module/getjobs",
                params={"start": page * 100 + 1, "count": 100, "k": keyword},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            try:
                payload = json.loads(resp)
            except (TypeError, ValueError):
                break
            if not isinstance(payload, dict) or int(payload.get("code") or 0) != 1:
                break
            items = payload.get("data") or []
            if not isinstance(items, list) or not items:
                break
            kept = [it for it in items if isinstance(it, dict) and it.get("publish_id")]
            out.extend(kept)
            if len(items) < 100:
                break
        return out

    def _detail(self, publish_id: str) -> str | None:
        if not self.fetch_detail:
            return None
        html = self.request_text("GET", f"{self.base}/detail/job", params={"id": publish_id})
        text = _text(html)
        i = text.find("职位详情")
        if i >= 0:
            text = text[i + len("职位详情"):]
        # 详情页正文里夹着导航与页脚，截到「单位信息」/「联系方式」之前
        stops = [text.find(s) for s in ("单位信息", "联系方式", "相关职位")]
        stops = [c for c in stops if c > 0]
        if stops:
            text = text[: min(stops)]
        text = re.sub(r"版权所有.*$", "", text).strip()
        return text or None

    def _collect(self, keyword: str, pages: int | None = None) -> list[dict]:
        out: list[dict] = []
        for item in self._list(keyword, pages):
            if any(same_company(item.get("company_name"), m) for m in self._matches()):
                out.append(item)
        return out

    def fetch_raw(self) -> Iterator[dict]:
        """先用公司全名做关键词检索；一条都没命中时退回「不带关键词全量翻页」。

        2026-10-30 实测：`k` 主要匹配岗位名，公司全名经常搜不到（同一个岗位列表
        用接口全量翻页能命中、带 k 反而 0 条），所以必须有这个兜底；兜底时翻得
        更深（fallback_pages，默认 10 页 = 1,000 条），否则长尾岗位落在第 6 页以后
        就永远抓不到。
        """
        explicit = str(self.source.params.get("keyword") or "")
        if explicit:
            keywords = [explicit]
        else:
            # 先试短公司名（接口对短名更宽松），再试登记全名，最后不带关键词全量翻页。
            keywords = [self.source.company, *self._matches()]
        for kw in keywords:
            found = self._collect(kw)
            if found:
                yield from found
                return
        if not explicit:
            yield from self._collect("", self.fallback_pages)

    def normalize(self, raw: dict) -> Job:
        pid = str(raw["publish_id"])
        title = _WS.sub(" ", str(raw.get("job_name") or "")).strip()
        if not title:
            raise SkipRecord("缺岗位名")
        is_intern = str(raw.get("is_practice") or "0") == "1"
        degree = raw.get("degree_require") or ""
        return Job(
            source_id=self.source.id,
            source_job_id=pid,
            company=self.source.company,
            url=f"{self.base}/detail/job?id={pid}",
            title=title,
            recruit_type="intern" if is_intern else "campus",
            cities=[raw["city_name"]] if raw.get("city_name") else [],
            degree_min=degree_min_from_text(degree) if degree else None,
            publish_at=date_only(raw.get("publish_time"), floor_year=2024),
            apply_end=date_only(raw.get("end_time"), floor_year=2024),
            description=self._detail(pid),
        )
