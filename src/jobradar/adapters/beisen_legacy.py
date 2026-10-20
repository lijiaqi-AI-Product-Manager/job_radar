"""北森旧版门户（服务端渲染，{tenant}.zhiye.com）变体 A。侦察：docs/recon/beisen.md §4.4

列表页 GET /{portal}/?PageIndex=N（N 从 1 开始；0 视为越界并返回第 1 页），每行：
  <tr><td><a title="算法工程师(J11995)" href="/zpdetail/311047502?PageIndex=1">…</a></td>
      <td title="所属单位">…</td><td title="江苏省-连云港市">…</td><td>2026-09-03</td></tr>
页脚"当前第N/M页"给出总页数。JD 原文暂不抓取（需逐个请求详情页）。
部分租户（如 kelun）详情链接为 /job_show/<id>，其余结构相同。

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
from jobradar.normalize import (
    batch_from_text,
    cities_from_text,
    grad_year_from_text,
    looks_like_location,
)

LIST_URL = "https://{tenant}.zhiye.com/{portal}/"
DETAIL_URL = "https://{tenant}.zhiye.com/{path}/{id}"
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
LINK = re.compile(r'<a[^>]*?title="([^"]+)"[^>]*?href="/(zpdetail|job_show)/(\d+)[^"]*"', re.I)
TD_TITLE = re.compile(r'<td[^>]*?title="([^"]*)"', re.I)
TOTAL_PAGES = re.compile(r"当前第\s*\d+\s*/\s*(\d+)\s*页")
MAX_PAGES = 200  # 防御：站点分页异常时不无限翻页


@register
class BeisenLegacyAdapter(Adapter):
    id = "beisen_legacy"

    def fetch_raw(self) -> Iterator[dict]:
        p = self.source.params
        url = LIST_URL.format(tenant=p["tenant"], portal=p.get("portal", "campus"))
        seen: set[str] = set()
        page, last = 1, MAX_PAGES
        while page <= last:
            html = self.request_text("GET", url, params={"PageIndex": page})
            m = TOTAL_PAGES.search(html)
            if m:
                last = min(int(m.group(1)), MAX_PAGES)
            new = 0
            for row in ROW.findall(html):
                link = LINK.search(row)
                if not link or link.group(3) in seen:
                    continue
                seen.add(link.group(3))
                new += 1
                # 各租户列顺序不一：按内容识别，地名列当城市，第一个非地名列当所属单位
                tds = [unescape(t).strip() for t in TD_TITLE.findall(row)]
                yield {"id": link.group(3), "path": link.group(2), "title": unescape(link.group(1)).strip(),
                       "org": next((t for t in tds if t and not looks_like_location(t)), None),
                       "city": next((t for t in tds if looks_like_location(t)), None)}
            if not new:  # 没有新岗位：已越过末页
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def normalize(self, raw: dict) -> Job:
        if not raw.get("id") or not raw.get("title"):
            raise SkipRecord
        p = self.source.params
        recruit_type = p.get("recruit_type", "campus")
        return Job(
            source_id=self.source.id,
            source_job_id=raw["id"],
            company=self.source.company,
            url=DETAIL_URL.format(tenant=p["tenant"], path=raw.get("path", "zpdetail"), id=raw["id"]),
            title=raw["title"],
            recruit_type=recruit_type,
            cities=cities_from_text(raw.get("city")),
            department=raw.get("org") or None,
            grad_year=grad_year_from_text(raw["title"]) if recruit_type != "social" else None,
            batch=batch_from_text(raw["title"]) if recruit_type == "campus" else None,
        )
