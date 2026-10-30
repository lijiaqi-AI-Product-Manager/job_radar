"""才立方公开招聘公告（聚合）；路径边界见 docs/recon/jysd.md。

params: host、match（登记主体全名）、title_terms、max_pages（默认 200）。
一条记录是一份公告，可能含多岗；学校过期时间不是雇主网申截止日。
"""

from __future__ import annotations

import base64
import binascii
import re
import threading
import time
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from html import escape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import (
    KNOWN_CITIES,
    batch_from_text,
    cities_from_text,
    date_only,
    grad_year_from_text,
)
from jobradar.timeutil import now_ts, shanghai_date

_WIDGET = re.compile(
    r'''\$\(["']#(content\d+)["']\)\.each\([\s\S]*?Base64\.decode\(unzip\("([^"\n]+)"\)'''
    r"\.substr\((\d+)\)\)\.substr\((\d+)\)"
)
_MAX_FRAGMENT = 2_000_000
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "embed", "source", "wbr", "col", "param"}
_BLOCK = {"p", "div", "section", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br"}
_CONTACT = re.compile(r"^(?:招聘|咨询|投递)?(?:联系人|联系电话|联系方式|手机|电话|邮箱|电子邮箱)")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(?:1[3-9]\d{9}|0\d{2,3}[-－]\d{7,8})(?!\d)")
_CAMPUS = re.compile(r"校园|校招|应届|毕业生|20\d{2}\s*届")
_DEADLINE = re.compile(
    r"(?:报名|网申|简历投递|在线申请)(?:截止(?:时间|日期)?|时间截至)[：:\s]*"
    r"(?:北京时间\s*)?(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?"
)


def public_html(html: str) -> str:
    """只展开页面给出的固定字面压缩 HTML，不执行脚本或推导请求参数。"""
    for match in list(_WIDGET.finditer(html)):
        ident, packed, first, second = match.groups()
        try:
            if len(packed) > _MAX_FRAGMENT or max(int(first), int(second)) > 4096:
                raise ValueError("压缩片段或字面截取范围过大")
            inflater = zlib.decompressobj()
            raw = inflater.decompress(base64.b64decode(packed, validate=True), _MAX_FRAGMENT + 1)
            if len(raw) > _MAX_FRAGMENT or not inflater.eof or inflater.unused_data:
                raise ValueError("压缩片段超限或不完整")
            content = base64.b64decode(raw.decode("utf-8")[int(first):], validate=True).decode("utf-8")
            content = content[int(second):]
        except (ValueError, zlib.error, binascii.Error, UnicodeError) as exc:
            raise ValueError("无法读取公开 HTML 压缩片段，不执行其他脚本") from exc
        placeholder = rf'<section\b[^>]*\bid=["\']{ident}["\'][^>]*>.*?</section>'
        html, count = re.subn(placeholder, lambda _, value=content: value, html, count=1, flags=re.S)
        if not count:
            raise ValueError("公开 HTML 片段没有对应的页面容器")
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def find(self, tag=None, cls=None):
        if (tag is None or self.tag == tag) and (cls is None or cls in self.attrs.get("class", "").split()):
            yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.find(tag, cls)

    def text(self):
        if self.tag in {"script", "style"}:
            return ""
        content = "".join(c.text() if isinstance(c, _Node) else c for c in self.children)
        return content + ("\n" if self.tag in _BLOCK else " " if self.tag in {"td", "th"} else "")

    def html(self):
        if self.tag in {"script", "style"}:
            return ""
        attrs = "".join(f' {k}="{escape(str(v), quote=True)}"' for k, v in self.attrs.items() if v is not None)
        body = "".join(c.html() if isinstance(c, _Node) else escape(c) for c in self.children)
        return f"<{self.tag}{attrs}>" + ("" if self.tag in _VOID else body + f"</{self.tag}>")


class _DOM(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.feed(public_html(html))

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _text(node):
    return " ".join(node.text().split()) if node else ""


def _date_in(text):
    match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    return date_only(match[0]) if match else None


def _same_public_url(url, base, path):
    parts, origin = urlsplit(url), urlsplit(base)
    if (parts.scheme != "https" or parts.netloc != origin.netloc or parts.username or parts.password
            or not parts.path.startswith(path) or "keyword=" in parts.query):
        raise ValueError("链接离开了已核实的同站公开招聘路径")
    return url


def parse_index(html: str, base: str) -> dict:
    root = _DOM(html).root
    container = next(root.find(cls="campus-index-front-list"), None)
    if container is None:
        raise ValueError("缺少公开招聘栏目，可能返回登录页或已改版")
    items = []
    for row in container.find("ul", "infoList"):
        link = next((a for a in row.find("a") if re.fullmatch(r"/campus/view/id/\d+", a.attrs.get("href", ""))), None)
        if link is None:
            continue
        url = _same_public_url(urljoin(base, link.attrs["href"]), base, "/campus/view/id/")
        stamp = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", row.text())
        items.append({"id": urlsplit(url).path.rsplit("/", 1)[-1], "title": _text(link), "url": url,
                      "published": date_only(stamp[0]) if stamp else None})
    if not items and not re.search(r"暂无(?:招聘|信息|数据|公告)", container.text()):
        raise ValueError("公开列表没有可识别的公告，不能当作空采集成功")
    nxt = next((n for n in root.find("li", "next") if "disabled" not in n.attrs.get("class", "").split()), None)
    link = next(nxt.find("a"), None) if nxt else None
    next_url = _same_public_url(urljoin(base, link.attrs.get("href", "")), base, "/campus/index") if link else None
    pager = [n for n in root.find("li", "page") if _text(n).isdigit()]
    current_node = next((n for n in pager if "selected" in n.attrs.get("class", "").split()), None)
    current_page = int(_text(current_node)) if current_node else None
    last_page = max((int(_text(n)) for n in pager), default=None)
    selected_link = next(current_node.find("a"), None) if current_node else None
    selected_url = urljoin(base, selected_link.attrs.get("href", "")) if selected_link else None
    if next_url and next_url == selected_url:
        if current_page == last_page:
            next_url = None  # 当前页=分页控件明示末页，才接受站点自己的 self-link。
        else:
            raise ValueError("公开索引在末页之前发生分页循环")
    return {"items": items, "next": next_url, "current_page": current_page, "last_page": last_page}


def _description(node):
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in node.text().splitlines()]
    text = "\n".join(line for line in lines if line and not _CONTACT.match(line))
    return _PHONE.sub("[联系方式已略]", _EMAIL.sub("[联系方式已略]", text))


def parse_detail(html: str) -> dict:
    root = _DOM(html).root
    title_block = next(root.find(cls="details-title"), None)
    body = next(root.find(cls="aContent"), None)
    if title_block is None or body is None:
        raise ValueError("公开公告详情结构缺失，可能返回登录页或已改版")
    heading = next((n for n in title_block.find() if n.tag in {"h1", "h2", "h3", "h4", "h5"}), None)
    company = next(title_block.find("a", "name"), None)
    expiry = next(title_block.find(cls="expired_time"), None)
    message = next(root.find(cls="title-message"), None)
    description = _description(body)
    deadlines = {date_only(f"{y}-{int(m):02d}-{int(d):02d}") for y, m, d in _DEADLINE.findall(description)} - {None}
    city = re.search(r"(?:工作地点|工作城市)[：:]\s*([^\n]{1,100})", description)
    location = re.split(r"学历要求|招聘人数|岗位职责|专业要求", city[1])[0] if city else ""
    published = re.search(r"发布时间[：:]\s*(20\d{2}-\d{2}-\d{2})", _text(title_block) + " " + _text(message))
    return {"title": _text(heading), "company": _text(company), "listing_end": _date_in(_text(expiry)),
            "published": date_only(published[1]) if published else None, "description": description,
            "apply_end": next(iter(deadlines)) if len(deadlines) == 1 else None,
            "cities": [c for c in cities_from_text(location) if c in KNOWN_CITIES]}


_INDEX_CACHE = {}
_INDEX_LOCK = threading.Lock()


@register
class JysdAdapter(Adapter):
    id = "jysd"

    @staticmethod
    def fixture_transform(content: bytes, content_type: str) -> bytes:
        """在任何落盘之前裁剪页面与联系方式；客户端仍收到原始响应。"""
        if "html" not in content_type.lower():
            return content
        html = content.decode("utf-8")
        root = _DOM(html).root
        container = next(root.find(cls="campus-index-front-list"), None)
        if container is not None:
            widgets = list(_WIDGET.finditer(html))
            if not widgets:
                return container.html().encode("utf-8")
            parts = ['<div class="campus-index-front-list">']
            for widget in widgets:
                parts += [f'<section id="{widget[1]}"></section>', '<script>' + widget[0] + ');});</script>']
            return ("".join(parts) + "</div>").encode("utf-8")
        header = next(root.find(cls="details-title"), None)
        body = next(root.find(cls="aContent"), None)
        if header is None or body is None:
            # 404 robots 页面或非预期 HTML 不保留；不让登录页的匿名字段进入 fixtures。
            return b""
        body.children = [_description(body)]
        message = next(root.find(cls="title-message"), None)
        minimized = header.html() + (message.html() if message else "") + body.html()
        return _PHONE.sub("REDACTED", _EMAIL.sub("REDACTED", minimized)).encode("utf-8")

    def __init__(self, *args, reference_date: date | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.reference_date = reference_date or date.fromisoformat(shanghai_date(now_ts()))

    def _index(self):
        base = "https://" + self.source.params["host"]
        limit = int(self.source.max_pages or 200)
        partial = bool(self.source.params.get("allow_partial"))
        key = (base, limit, partial)
        with _INDEX_LOCK:
            cached = _INDEX_CACHE.get(key)
            if cached and time.monotonic() - cached[0] < 600:
                return cached[1]
            rows, seen, pages = [], set(), set()
            url = base + "/campus/index"
            for _ in range(limit):
                if url in pages:
                    raise ValueError("公开列表分页重复，停止该源")
                pages.add(url)
                parsed = parse_index(self.request_text("GET", url), base)
                fresh = [r for r in parsed["items"] if r["id"] not in seen]
                if parsed["items"] and not fresh:
                    raise ValueError("公开列表内容重复，停止该源")
                rows.extend(fresh)
                seen.update(r["id"] for r in fresh)
                url = parsed["next"]
                if not url:
                    break
            if url and not partial:
                raise ValueError("公开索引超过 max_pages，未完成采集，不能据此下架岗位")
            _INDEX_CACHE[key] = (time.monotonic(), rows)
            return rows

    def fetch_raw(self) -> Iterator[dict]:
        terms = self.source.params.get("title_terms") or [self.source.company]
        for item in self._index():
            if not any(str(term).casefold() in item["title"].casefold() for term in terms):
                continue
            yield {"item": item, "detail": parse_detail(self.request_text("GET", item["url"]))}

    def normalize(self, raw: dict) -> Job:
        item, detail = raw["item"], raw["detail"]
        matches = self.source.params.get("match")
        matches = [matches] if isinstance(matches, str) else matches
        if not matches:
            raise ValueError("jysd 必须配置已核实的登记主体全名 match")
        if detail["company"] not in matches:
            raise SkipRecord("公告登记主体不匹配")
        if detail["listing_end"] and detail["listing_end"] < self.reference_date.isoformat():
            raise SkipRecord("学校公告已过期；不把过期日伪装成网申截止日")
        title = detail["title"]
        if not title or not _CAMPUS.search(title):
            raise SkipRecord("不是标题明示的校园/应届招聘公告")
        if not detail["description"]:
            raise ValueError("公告正文缺失，不能作为健康采集结果")
        return Job(source_id=self.source.id, source_job_id=item["id"], company=self.source.company,
                   url=item["url"], title=title, recruit_type="campus", grad_year=grad_year_from_text(title, loose=True),
                   batch=batch_from_text(title), cities=detail["cities"], degree_min=None,
                   publish_at=detail["published"] or item.get("published"), apply_end=detail["apply_end"],
                   description=detail["description"])
