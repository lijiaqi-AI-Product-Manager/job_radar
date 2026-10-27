"""北森旧版门户（服务端渲染，{tenant}.zhiye.com）变体 A。侦察：docs/recon/beisen.md §4.4

列表页 GET /{portal}/?PageIndex=N（N 从 1 开始；0 视为越界并返回第 1 页），每行：
  <tr><td><a title="算法工程师(J11995)" href="/zpdetail/311047502?PageIndex=1">…</a></td>
      <td title="所属单位">…</td><td title="江苏省-连云港市">…</td><td>2026-09-03</td></tr>
页脚"当前第N/M页"给出总页数。JD 原文逐个请求详情页 /zpdetail/<id>：
  <p class="title">工作职责：</p><p>…</p> … <p class="title">任职资格：</p><p>…</p>
部分租户（如 kelun）详情链接为 /job_show/<id>，其余结构相同。

变体 C（社招门户 `/{portal}/` 里的 `/socialxq?jobId=<id>` 链接，如 zofund/cnpc）：
表格列是「岗位 / 部门 / 体系 / 城市 / 时间」，详情页 `/socialxq?jobId=<id>`：
  <h2 class="f14 …">工作职责：</h2><div class="col333 f14 lh25">…<br />…</div>
  <h2 class="f14 …">任职资格：</h2><div class="col333 f14 lh25">…</div>
与变体 A 的区别只有两点：详情路径是 `/{portal}xq`、章节标题在 `<h2>` 里且带冒号。
2026-10-27 由 work/site_ats.py 从官网反查发现（zofund 等 12 家），此前 A 变体的
`/zpdetail/` 正则匹配不到，这些社招门户一直被当成「空租户」。

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


A_DESC = "工作职责|岗位职责|职位描述|职责描述|工作内容"
A_REQ = "任职资格|任职要求|职位要求|岗位要求"
# 变体 C：列表行是 <a href="/socialxq?jobId=123"><span>标题</span></a>：<a href="/socialxq?jobId=123"><span>标题</span></a>
C_LINK = re.compile(r'<a href="/(socialxq|campusxq|internxq)\?jobId=(\d+)"[^>]*>(.*?)</a>', re.S | re.I)
C_TITLE = re.compile(r"<span[^>]*>([^<]+)</span>", re.I)


def _text(fragment: str) -> str | None:
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = unescape(TAG.sub("", text))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()) or None


def _section(html: str, name: str) -> str | None:
    """变体 B 详情页中 <h3>{name}</h3><div class="xqm">…</div> 的纯文本。"""
    m = re.search(rf'<h3[^>]*>\s*{name}\s*</h3>\s*<div class="xqm">(.*?)</div>', html, re.S | re.I)
    return _text(m.group(1)) if m else None


def _c_section(html: str, labels: str) -> str | None:
    """变体 C 详情页 `<h2>工作职责：</h2><div>…</div>` 的纯文本。"""
    m = re.search(rf"<h2[^>]*>\s*(?:{labels})\s*[：:]?\s*</h2>\s*<div[^>]*>(.*?)</div>",
                  html, re.S | re.I)
    return _text(m.group(1)) if m else None


def _a_section(html: str, labels: str) -> str | None:
    """变体 A 详情页中 <p>{标签}：</p><p>…</p> 的纯文本。"""
    m = re.search(rf"<p[^>]*>\s*(?:{labels})\s*[：:]?\s*</p>\s*<p[^>]*>(.*?)</p>", html, re.S | re.I)
    return _text(m.group(1)) if m else None


DATE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")


def _date_in(html: str) -> str | None:
    """列表页行内的发布日期，取最靠后的那个 `20xx-xx-xx`。

    行内只有一个日期（发布日期），但 `title` 属性里偶有年份字样，
    所以只认 `YYYY-MM-DD` 完整形态，取最后一个（列顺序里发布日期在最后）。
    """
    hits = DATE.findall(html)
    if not hits:
        return None
    y, m, d = hits[-1]
    try:
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except ValueError:
        return None


@register
class BeisenLegacyAdapter(Adapter):
    id = "beisen_legacy"

    def fetch_raw(self) -> Iterator[dict]:
        if self.source.params.get("variant") == "b":
            yield from self._fetch_variant_b()
            return
        if self.source.params.get("variant") == "c":
            yield from self._fetch_variant_c()
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
                detail = self.request_text("GET", DETAIL_URL.format(
                    tenant=p["tenant"], path=link.group(2), id=link.group(3)))
                # 列表页最后一列是发布日期 `2026-09-03`（实测 yumchina/goodix 都有）。
                # 这是页面明写给用户看的信息，不是推测，可以进 publish_at。
                # 解析失败一律当没有，不猜。
                yield {"id": link.group(3), "path": link.group(2), "title": unescape(link.group(1)).strip(),
                       "org": next((t for t in tds if t and not looks_like_location(t)), None),
                       "city": next((t for t in tds if looks_like_location(t)), None),
                       "publish_at": _date_in(row),
                       "description": _a_section(detail, A_DESC),
                       "requirements": _a_section(detail, A_REQ)}
            if not new:  # 没有新岗位：已越过末页
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def _fetch_variant_c(self) -> Iterator[dict]:
        """社招门户（`/socialxq?jobId=`）：列表是表格，详情页章节在 `<h2>` 里。"""
        p = self.source.params
        portal = p.get("portal", "social")
        url = LIST_URL.format(tenant=p["tenant"], portal=portal)
        seen: set[str] = set()
        page = 1
        while page <= MAX_PAGES:
            html = self.request_text("GET", url, params={"PageIndex": page})
            new = 0
            for row in ROW.findall(html):
                link = C_LINK.search(row)
                if not link or link.group(2) in seen:
                    continue
                seen.add(link.group(2))
                new += 1
                m = C_TITLE.search(link.group(3))
                title = unescape(m.group(1) if m else TAG.sub("", link.group(3))).strip()
                # 同一行里除标题外的列：部门 / 体系 / 城市 / 日期，按内容识别城市
                cells = [unescape(TAG.sub("", c)).strip() for c in
                         re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
                # 详情是查询串形式 `/{path}?jobId=`。不能套用 `/{path}/{id}` 的路径模板——
                # 服务端对 `/socialxq/123` 也回 200，但返回的是**没有 JD 的空壳页**，
                # 静默丢正文（2026-10-27 实测踩到，第一版 6 个岗位 JD 全是 None）。
                detail = self.request_text(
                    "GET", f"https://{p['tenant']}.zhiye.com/{link.group(1)}",
                    params={"jobId": link.group(2)})
                yield {"id": link.group(2), "path": link.group(1), "title": title,
                       "org": next((c for c in cells[1:] if c and not looks_like_location(c)
                                    and not DATE.search(c)), None),
                       "city": next((c for c in cells if looks_like_location(c)), None),
                       "publish_at": _date_in(row),
                       "description": _c_section(detail, A_DESC),
                       "requirements": _c_section(detail, A_REQ)}
            if not new:
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
        # 变体 C 的门户本身就是社招（/socialxq），再退化成 campus 会把社招岗错标成校招；
        # 未显式写 recruit_type 时按 portal 名推断（social/intern/campus）
        recruit_type = p.get("recruit_type") or (
            p.get("portal") if p.get("portal") in ("social", "intern", "campus") else "campus")
        return Job(
            source_id=self.source.id,
            source_job_id=raw["id"],
            company=self.source.company,
            url=(f"https://{p['tenant']}.zhiye.com/{raw['path']}?jobId={raw['id']}"
                 if raw.get("path", "").endswith("xq") and raw.get("path") != "campusxq"
                 else B_DETAIL_URL.format(tenant=p["tenant"], id=raw["id"])
                 if raw.get("path") == "campusxq"
                 else DETAIL_URL.format(tenant=p["tenant"], path=raw.get("path", "zpdetail"),
                                       id=raw["id"])),
            title=raw["title"],
            recruit_type=recruit_type,
            cities=cities_from_text(raw.get("city")),
            department=raw.get("org") or None,
            grad_year=grad_year_from_text(raw["title"]) if recruit_type != "social" else None,
            batch=batch_from_text(raw["title"]) if recruit_type == "campus" else None,
            degree_min=degree_min_from_text(raw.get("degree")),
            description=raw.get("description"),
            requirements=raw.get("requirements"),
            publish_at=raw.get("publish_at"),
        )
