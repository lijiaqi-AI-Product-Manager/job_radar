"""北森旧版门户（服务端渲染，{tenant}.zhiye.com）变体 A。侦察：docs/recon/beisen.md §4.4

列表页 GET /{portal}/?PageIndex=N（N 从 1 开始；0 视为越界并返回第 1 页），每行：
  <tr><td><a title="算法工程师(J11995)" href="/zpdetail/311047502?PageIndex=1">…</a></td>
      <td title="所属单位">…</td><td title="江苏省-连云港市">…</td><td>2026-09-03</td></tr>
页脚"当前第N/M页"给出总页数。JD 原文暂不抓取（需逐个请求详情页）。
部分租户（如 kelun）详情链接为 /job_show/<id>，其余结构相同。

变体 B（params.variant = "b"，如 smics）：每个岗位是
  <a href="/campusxq?jobId=<id>&jc=2…"><span>分类</span><span>标题</span><span>学历</span><span>地点</span>…</a>
标题超长时被截断为"…(J133..."，因此逐个请求详情页 /campusxq?jobId=<id>&jc=2，取完整标题（h2）与职位描述/要求。

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
    degree_min_from_text,
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
B_LINK = re.compile(r'<a href="/campusxq\?jobId=(\d+)[^"]*"[^>]*>(.*?)</a>', re.S | re.I)
B_SPAN = re.compile(r"<span[^>]*>([^<]*)</span>", re.I)
B_DETAIL_URL = "https://{tenant}.zhiye.com/campusxq?jobId={id}&jc=2"
B_TITLE = re.compile(r'<h2 class="\s*col26[^"]*"[^>]*>([^<]+)</h2>', re.I)
TAG = re.compile(r"<[^>]+>")


def _section(html: str, name: str) -> str | None:
    """详情页中 <h3>{name}</h3><div class="xqm">…</div> 的纯文本。"""
    m = re.search(rf'<h3[^>]*>\s*{name}\s*</h3>\s*<div class="xqm">(.*?)</div>', html, re.S | re.I)
    if not m:
        return None
    text = re.sub(r"<br\s*/?>", "\n", m.group(1), flags=re.I)
    text = unescape(TAG.sub("", text))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()) or None


@register
class BeisenLegacyAdapter(Adapter):
    id = "beisen_legacy"

    def fetch_raw(self) -> Iterator[dict]:
        if self.source.params.get("variant") == "b":
            yield from self._fetch_variant_b()
            return
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

    def _fetch_variant_b(self) -> Iterator[dict]:
        p = self.source.params
        url = LIST_URL.format(tenant=p["tenant"], portal=p.get("portal", "campus"))
        seen: set[str] = set()
        page = 1
        while page <= MAX_PAGES:
            html = self.request_text("GET", url, params={"PageIndex": page})
            new = 0
            for job_id, inner in B_LINK.findall(html):
                if job_id in seen:
                    continue
                seen.add(job_id)
                new += 1
                spans = [unescape(s).strip() for s in B_SPAN.findall(inner)]
                if len(spans) < 2:
                    continue
                detail = self.request_text("GET", B_DETAIL_URL.format(tenant=p["tenant"], id=job_id))
                full = B_TITLE.search(detail)
                yield {"id": job_id, "path": "campusxq",
                       "title": unescape(full.group(1)).strip() if full else spans[1],
                       "org": spans[0] or None,
                       "degree": spans[2] if len(spans) > 2 else None,
                       "city": next((t for t in spans[2:] if looks_like_location(t)), None),
                       "description": _section(detail, "职位描述"),
                       "requirements": _section(detail, "职位要求")}
            if not new:
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
            url=(B_DETAIL_URL.format(tenant=p["tenant"], id=raw["id"]) if raw.get("path") == "campusxq"
                 else DETAIL_URL.format(tenant=p["tenant"], path=raw.get("path", "zpdetail"), id=raw["id"])),
            title=raw["title"],
            recruit_type=recruit_type,
            cities=cities_from_text(raw.get("city")),
            department=raw.get("org") or None,
            grad_year=grad_year_from_text(raw["title"]) if recruit_type != "social" else None,
            batch=batch_from_text(raw["title"]) if recruit_type == "campus" else None,
            degree_min=degree_min_from_text(raw.get("degree")),
            description=raw.get("description"),
            requirements=raw.get("requirements"),
        )
