"""阿里巴巴校园招聘 campus-talent.alibaba.com（应届生/实习生）。侦察：docs/recon/alibaba.md

匿名会话（docs/DEVELOPMENT.md 铁律 1，2026-10-21 用户批准）：先打开公开职位页，站点给匿名访客下发会话 cookie，
页面内嵌 `__token__`；列表接口 `POST /position/search?_csrf=<token>` 带着它即可访问。token 只在内存里。
批次（应届生/实习生/顶尖人才计划）从 `POST /searchCondition/listBatch` 取，不写死届别。
列表直接含职责（description）与要求（requirement）原文，无需详情请求。

source.params:
  base_url: 站点根，默认 https://campus-talent.alibaba.com（阿里云、淘天等子站同一套系统时可换）
  channel: 渠道标识，默认 campus_group_official_site
  page_size: 每页条数，默认 20（录 fixtures 时用小值）
"""

import re
from collections.abc import Iterator

import httpx

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import cities_from_text, date_only, grad_year_from_text

BASE_URL = "https://campus-talent.alibaba.com"
CHANNEL = "campus_group_official_site"
PAGE_SIZE = 20
TOKEN_RE = r'__token__["\']?\s*:\s*["\']([^"\']+)'
# listBatch 的分组 -> recruit_type
GROUP_TYPE = {"graduate": "campus", "topTalentPlan": "campus", "internship": "intern"}


@register
class AlibabaAdapter(Adapter):
    id = "alibaba"
    secret_patterns = [TOKEN_RE]

    def _base(self) -> str:
        return self.source.params.get("base_url", BASE_URL).rstrip("/")

    def fetch_raw(self) -> Iterator[dict]:
        try:
            yield from self._fetch()
        except httpx.HTTPStatusError as e:
            # 异常信息里的 URL 带 token：只报路径与状态码，不让 token 进日志/健康报告
            raise RuntimeError(f"alibaba {e.request.url.path} HTTP {e.response.status_code}") from None

    def _fetch(self) -> Iterator[dict]:
        base = self._base()
        page_url = f"{base}/campus/position"
        m = re.search(TOKEN_RE, self.request_text("GET", page_url))
        if not m:
            raise RuntimeError("alibaba: page token not found (site changed?)")
        params = {"_csrf": m.group(1)}
        headers = {"Referer": page_url, "Origin": base}
        channel = self.source.params.get("channel", CHANNEL)
        size = int(self.source.params.get("page_size", PAGE_SIZE))

        # 必须带 JSON 请求体（不带时 403，第 39 轮）
        batches = self.request_json("POST", f"{base}/searchCondition/listBatch", params=params, headers=headers,
                                    json={"channel": channel, "language": "zh"})
        if not batches.get("success"):
            raise RuntimeError(f"alibaba listBatch failed: {batches.get('errorMsg')}")
        seen_batches = set()
        for group, items in (batches.get("content") or {}).items():
            rtype = GROUP_TYPE.get(group)
            if rtype is None or not isinstance(items, list):
                continue
            for b in items:
                if not b.get("id") or b["id"] in seen_batches:
                    continue
                seen_batches.add(b["id"])
                yield from self._batch(base, params, headers, channel, size, b, rtype)

    def _batch(self, base, params, headers, channel, size, batch, rtype) -> Iterator[dict]:
        page = 1
        while True:
            data = self.request_json("POST", f"{base}/position/search", params=params, headers=headers, json={
                "batchId": batch["id"], "pageIndex": page, "pageSize": size, "channel": channel, "language": "zh",
            })
            if not data.get("success"):
                raise RuntimeError(f"alibaba position/search failed: {data.get('errorMsg')}")
            content = data.get("content") or {}
            items = content.get("datas") or []
            for item in items:
                yield {**item, "_recruit_type": rtype, "_batch_name": batch.get("name") or item.get("batchName")}
            total = content.get("totalCount") or 0
            if not items or page * size >= total:
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def normalize(self, raw: dict) -> Job:
        if not raw.get("id") or not (raw.get("name") or "").strip():
            raise SkipRecord
        rtype = raw.get("_recruit_type")
        if rtype not in ("campus", "intern"):
            raise SkipRecord
        cities: list[str] = []
        for loc in raw.get("workLocations") or []:
            for c in cities_from_text(loc) or [loc.strip()]:
                if c and c not in cities:
                    cities.append(c)
        batch_name = raw.get("_batch_name") or ""
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw["id"]),
            company=self.source.company,
            url=f"{self._base()}/campus/position/{raw['id']}",
            title=raw["name"].strip(),
            recruit_type=rtype,
            # 届别只取批次名里写明的（如「阿里巴巴2027届应届生」），实习批次不写届别则留空
            grad_year=grad_year_from_text(batch_name),
            cities=cities,
            department=" / ".join(raw.get("circleNames") or []) or None,
            # publishTime 实测恒为 null，modifyTime 是"最近修改"（数量级上按天分布，不是批量刷新），
            # 只能当"最晚上架日"的弱证据——所以填 publish_at 而不是当截止日。
            publish_at=date_only(raw.get("publishTime") or raw.get("modifyTime")),
            description=(raw.get("description") or "").strip() or None,
            requirements=(raw.get("requirement") or "").strip() or None,
        )
