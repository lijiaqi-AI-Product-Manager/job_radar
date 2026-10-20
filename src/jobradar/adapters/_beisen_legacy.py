"""北森旧版门户（服务端渲染，{tenant}.zhiye.com）变体 A。侦察：docs/recon/beisen.md §4.4

列表页 GET /{portal}/?PageIndex=N，岗位链接形如
  <a title="算法工程师(J11995)" href="/zpdetail/311047502?PageIndex=0">
列表只有标题与 id，JD 原文暂不抓取（需逐个请求详情页）。

source.params:
  tenant: 子域名，如 "cssc"
  portal: 列表路径，默认 "campus"（另有 "Intern" 等）
  recruit_type: 该门户对应的招聘类型，默认 campus
"""

import re
from collections.abc import Iterator
from html import unescape

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, grad_year_from_text

LIST_URL = "https://{tenant}.zhiye.com/{portal}/"
DETAIL_URL = "https://{tenant}.zhiye.com/zpdetail/{id}"
LINK = re.compile(r'<a[^>]*?title="([^"]+)"[^>]*?href="/zpdetail/(\d+)[^"]*"', re.I)
MAX_PAGES = 200  # 防御：站点分页异常时不无限翻页


@register
class BeisenLegacyAdapter(Adapter):
    id = "beisen_legacy"

    def fetch_raw(self) -> Iterator[dict]:
        p = self.source.params
        url = LIST_URL.format(tenant=p["tenant"], portal=p.get("portal", "campus"))
        seen: set[str] = set()
        page = 0
        while page < MAX_PAGES:
            html = self.request_text("GET", url, params={"PageIndex": page})
            new = [(t, i) for t, i in LINK.findall(html) if i not in seen]
            if not new:  # 翻过最后一页时站点会重复返回末页或空页
                return
            for title, job_id in new:
                seen.add(job_id)
                yield {"id": job_id, "title": unescape(title).strip()}
            page += 1
            if self.source.max_pages and page >= self.source.max_pages:
                return

    def normalize(self, raw: dict) -> Job:
        if not raw.get("id") or not raw.get("title"):
            raise SkipRecord
        p = self.source.params
        recruit_type = p.get("recruit_type", "campus")
        return Job(
            source_id=self.source.id,
            source_job_id=raw["id"],
            company=self.source.company,
            url=DETAIL_URL.format(tenant=p["tenant"], id=raw["id"]),
            title=raw["title"],
            recruit_type=recruit_type,
            grad_year=grad_year_from_text(raw["title"]) if recruit_type != "social" else None,
            batch=batch_from_text(raw["title"]) if recruit_type == "campus" else None,
        )
