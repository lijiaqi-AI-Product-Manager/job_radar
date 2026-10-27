"""Avature 招聘站（`careers.<公司>.com/<lang>/careers/JobDetail/…`）。

侦察：docs/recon/avature.md。服务端渲染 HTML，匿名可读，无登录、无签名、无验证码。

为什么走 **sitemap** 而不是搜索接口：
  `/{lang}/careers/sitemap.xml` 由 robots.txt 自己 `Sitemap:` 声明（等于站点邀请抓），
  一次请求给出全部岗位 URL。而 `/{lang}/careers/SearchJobs` 是带 `qtvc=` 会话参数的分页接口，
  robots.txt 里 `Disallow: /careers/*qtvc=` 正是要挡它 —— 能不能构造出来是一回事，
  站点明确不想让人翻页是另一回事。sitemap 路线既合规又省请求。

页面形态（2026-10-26 实测达能 careers.danone.com.cn）：

    <h2 class="banner__title">Project Manager - IPRO</h2>
    <div class="banner__text__fields">
      <p class="banner--field">
        <span class="banner--field--icon banner--field--icon-location"></span> 上海
      </p>
      <p class="banner--field">
        <span class="banner--field--icon banner--field--icon-time"></span> 全职
      </p>
    </div>
    …
    <div class="article__content"> 正文（含「岗位职责和要求」标题 + 富文本） </div>

地点用 icon class 区分（`--location` / `--time`），不靠位置猜。

source.params:
  base:    站点根，如 "https://careers.danone.com.cn"
  lang:    语言段，如 "zh_CN"
  sitemap: sitemap 路径，默认 "{lang}/careers/sitemap.xml"
  path_re: 只收匹配这个正则的 URL（默认只收 JobDetail）
"""

import html
import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import cities_from_text, city_from_english, date_only, grad_year_from_text

DEFAULT_SITEMAP = "{lang}/careers/sitemap.xml"
# 只收岗位详情页。sitemap 里混着 Login / ProfileEdit / ApplicationForm / Error 这些**账户页**，
# 它们匿名访问会 403（2026-10-26 实测 `/careers/Error` 直接 403 让整轮抓取崩掉）。
# 所以必须是 `JobDetail/` 且 URL 末段是纯数字（`…/JobDetail/10283` 或 `…/JobDetail/slug/10283`）。
DEFAULT_PATH_RE = r"/careers/JobDetail/(?:[^/]+/)?\d+$"
# **站点版式 B：达能全球站**（`careers.danone.com/en-global/jobs/<slug>-<id>-en-us.html`）。
# 同一套 Avature 后台，但走 AEM 渲染，class 名和日期格式全换了：
#   <article class="cmp-contentfragment …" country="Malaysia" city="Kuala Lumpur"
#            positionType="Permanent Full-Time" description="<ul>…">
#   <h1>岗位名</h1>  <span class="dn-jobdetails__posteddate"> Posted: 22 Oct 2026 </span>
#   <div class="dn-jobdetails__description-body"> 正文 </div>
# URL 也不含 `JobDetail/`，所以 path_re 要换。见 docs/recon/avature.md §7。
GLOBAL_PATH_RE = r"/jobs/(?:[^/]+)-(\d+)-(?:en|zh|fr|es|de|ja|ko|th|vi|id)(?:-[a-z]{2})?\.html$"
LOC_RE = re.compile(r'<loc>(?P<u>[^<]+)</loc>')
TITLE = re.compile(r'<h2 class="banner__title"[^>]*>(?P<t>.*?)</h2>', re.S)
# 地点：icon class 里带 `--location` 的那个 banner--field
LOCATION = re.compile(
    r'<p class="banner--field"[^>]*>\s*'
    r'<span class="[^"]*banner--field--icon-location[^"]*"[^>]*>\s*</span>(?P<v>.*?)</p>',
    re.S,
)
JOB_TYPE = re.compile(
    r'<p class="banner--field"[^>]*>\s*'
    r'<span class="[^"]*banner--field--icon-time[^"]*"[^>]*>\s*</span>(?P<v>.*?)</p>',
    re.S,
)
# 正文：article__content 一直取到 `</article>`（里面嵌套的 div 太多，非贪婪会提前停）
DESC = re.compile(r'<div class="article__content"[^>]*>(?P<body>.*?)</article>', re.S)
# og:description 是首段摘要，正文抽不出来时的兜底
OG_DESC = re.compile(r'<meta property="og:description" content="(?P<v>[^"]*)"')
# meta Description 里带发布日期：`Project Manager - IPRO at  created 21-Oct-2026`
META_DATE = re.compile(r"created\s+(?P<d>\d{1,2}-[A-Za-z]{3}-\d{4})")
CATEGORY = re.compile(r'<div class="banner__text__subtitle"[^>]*>(?P<v>.*?)</div>', re.S)

# ---- 版式 B（达能全球站，AEM 渲染）的选择器 ----
G_TITLE = re.compile(r'<div class="dn-jobdetails__meta-head"[^>]*>\s*<h1[^>]*>(?P<t>.*?)</h1>', re.S)
# <article … country="…" city="…" positionType="…" description="&lt;ul>…">
# `description` 自己**含 `>`**（`&lt;ul>` 解出来就是 `<ul>`），所以属性值的字符类必须排除引号而非 `>`，
# 并且整段属性要用「到明显的属性边界」为止 —— 用 `[^>]*` 会在第一个 `>` 处截断，
# 结果 description 只拿到半截（2026-10-26 实测）。
G_ARTICLE = re.compile(r"<article class=\"cmp-contentfragment[^\"]*\"(?P<attrs>(?:\s+[\w-]+=\"[^\"]*\")*)\s*/?>", re.S)
G_ATTR = re.compile(r'(?P<k>[\w-]+)="(?P<v>[^"]*)"')
# 发布日期：`Posted: 22 Oct 2026`（dd MMM yyyy），与版式 A 的 `21-Oct-2026` 不同
G_DATE = re.compile(r'class="dn-jobdetails__posteddate"[^>]*>(?P<v>.*?)</span>', re.S)
G_DATE_TEXT = re.compile(r"(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3})[a-z]*\.?\s+(?P<y>\d{4})")
G_DESC = re.compile(r'<div class="dn-jobdetails__description-body"[^>]*>(?P<body>.*?)</div>\s*</div>\s*</div>', re.S)
TAG = re.compile(r"<[^>]+>")
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _text(fragment: str | None) -> str | None:
    if not fragment:
        return None
    s = html.unescape(TAG.sub(" ", fragment))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    return s or None


def _dd_mon_yyyy(value: str | None) -> str | None:
    """`21-Oct-2026` -> `2026-10-21`。月份名认不出来就返回 None——不猜。"""
    if not value:
        return None
    m = re.fullmatch(r"(?P<d>\d{1,2})-(?P<mon>[A-Za-z]{3})-(?P<y>\d{4})", value.strip())
    if not m:
        return None
    mon = _MONTHS.get(m.group("mon").lower())
    if not mon:
        return None
    return f"{int(m.group('y')):04d}-{mon:02d}-{int(m.group('d')):02d}"


def _d_mon_yyyy(value: str | None) -> str | None:
    """`Posted: 22 Oct 2026` -> `2026-10-22`（版式 B）。

    不能复用 `_dd_mon_yyyy`：那边是 `dd-MMM-yyyy` 带连字符，这里月名是全称缩写 + 空格，
    而且前面还挂着 "Posted: " 前缀。两个都写成「先取出日期片段、再解析」更稳。
    """
    if not value:
        return None
    s = _text(value) or ""
    m = G_DATE_TEXT.search(s)
    if not m:
        return None
    mon = _MONTHS.get(m.group("mon").lower())
    if not mon:
        return None
    return f"{int(m.group('y')):04d}-{mon:02d}-{int(m.group('d')):02d}"


def _g_attrs(detail: str) -> dict[str, str]:
    """版式 B 的字段全挂在 `<article>` 的属性上（country / city / positionType / description）。

    `description` 是被 HTML 转义过的整段正文 —— 比 `<div>` 嵌套更好抽，但**必须先 unescape**，
    否则 `&lt;li>` 会原样留在正文里。
    """
    m = G_ARTICLE.search(detail)
    if not m:
        return {}
    return {k: html.unescape(v) for k, v in G_ATTR.findall(m.group("attrs"))}


@register
class AvatureAdapter(Adapter):
    id = "avature"

    def _sitemap_url(self) -> str:
        p = self.source.params
        rel = (p.get("sitemap") or DEFAULT_SITEMAP).format(**p)
        return f"{p['base'].rstrip('/')}/{rel.lstrip('/')}"

    def fetch_raw(self) -> Iterator[dict]:
        p = self.source.params
        path_re = re.compile(p.get("path_re") or DEFAULT_PATH_RE)
        body = self.request_text("GET", self._sitemap_url())
        # sitemap 可能是个 sitemapindex（指向若干子 sitemap）。只跟一层，够用且不会失控。
        # 顺序很重要：先把「哪些是子 sitemap」记下来，再统一用 path_re 过滤岗位 URL —— 
        # 2026-10-26 踩过：只过滤主 sitemap 的 loc，子 sitemap 拉回来的 74 条全是账户页，
        # 第一条 `/careers/Error` 直接 403，整轮抓取崩掉。
        locs = LOC_RE.findall(body)
        subs = [u for u in locs if u.endswith(".xml")]
        urls = list(locs)
        for sub in subs:
            urls += LOC_RE.findall(self.request_text("GET", sub))
        # 子 sitemap 里也可能混着账户页（2026-10-26 实测达能 zh_CN sitemap 里同时有
        # `/careers/Login`、`/careers/AgentCreate`、`/careers/Error`）。过滤必须发生在
        # **所有** loc 汇总之后，任何一处漏过都会让整轮 403 挂掉。
        urls = [u for u in urls if path_re.search(u)]
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            try:
                detail = self.request_text("GET", url)
            except Exception:  # noqa: BLE001 — 单条详情 403/超时不该让整个源失败
                # sitemap 会随招聘周期留在缓存里，岗位下线后 URL 还在（Return404/Expired）。
                # 这种情况丢这一条，剩下的照常入库。整轮崩掉是更坏的结果：一个失效 URL
                # 会让 73 条有效岗位全部丢掉（2026-10-26 实测达能）。
                continue
            yield {"url": url, "detail": detail}

    def normalize(self, raw: dict) -> Job:
        detail = raw.get("detail") or ""
        if self.source.params.get("layout") == "global":
            return self._normalize_global(raw, detail)
        t = TITLE.search(detail)
        title = _text(t.group("t")) if t else None
        if not title:
            raise SkipRecord
        url = raw["url"]
        # 主键取 URL 末段（`…/JobDetail/slug/10283` 或 `…/JobDetail/10283`）
        jid = url.rstrip("/").rsplit("/", 1)[-1]
        if not jid.isdigit():
            raise SkipRecord
        loc = LOCATION.search(detail)
        place = _text(loc.group("v")) if loc else None
        jtype = JOB_TYPE.search(detail)
        desc = DESC.search(detail)
        desc_text = _text(desc.group("body")) if desc else None
        if not desc_text:
            og = OG_DESC.search(detail)
            desc_text = html.unescape(og.group("v")) if og else None
        meta_date = META_DATE.search(detail)
        cat = CATEGORY.search(detail)
        return Job(
            source_id=self.source.id,
            source_job_id=jid,
            company=self.source.company,
            url=url,
            title=title,
            recruit_type=_recruit_type(title, _text(jtype.group("v")) if jtype else ""),
            grad_year=grad_year_from_text(title),
            cities=cities_from_text(place) if place else [],
            department=_text(cat.group("v")) if cat else None,
            publish_at=_dd_mon_yyyy(meta_date.group("d")) if meta_date else date_only(None),
            description=desc_text,
        )

    def _normalize_global(self, raw: dict, detail: str) -> Job:
        """版式 B（达能全球站 `careers.danone.com/en-global/jobs/…`）。

        三个字段来自 `<article>` 的属性而不是 HTML 结构：
          `city="Kuala Lumpur"`、`positionType="Permanent Full-Time"`、
          `description="<ul><li>…"`（转义过的正文）。
        标题另有 `dn-jobdetails__meta-head` 里那个 `<h1>`（页面上还有一个面包屑用的 `<h1>Data</h1>`，
        所以不能取第一个 h1）。
        """
        url = raw["url"]
        # 主键在 URL 里：`<slug>-25905-en-us.html` -> 25905
        idm = re.search(r"-(?P<id>\d+)-\w+(?:-\w+)?\.html$", url)
        if not idm:
            raise SkipRecord
        jid = idm.group("id")
        attrs = _g_attrs(detail)
        t = G_TITLE.search(detail)
        title = _text(t.group("t")) if t else None
        if not title:
            raise SkipRecord
        city = (attrs.get("city") or "").strip()
        ptype = attrs.get("positionType") or ""
        body = attrs.get("description") or ""
        if not body:
            d = G_DESC.search(detail)
            body = d.group("body") if d else ""
        desc_text = _text(body) if body else None
        date_m = G_DATE.search(detail)
        return Job(
            source_id=self.source.id,
            source_job_id=jid,
            company=self.source.company,
            url=url,
            title=title,
            recruit_type=_recruit_type(title, ptype),
            grad_year=grad_year_from_text(title),
            # 全球站的 city 是英文城市名："Kuala Lumpur" / "Shanghai"。
            # cities_from_text 只认中文，英文串要交给 city_from_english 做映射。
            cities=_global_cities(city),
            department=(attrs.get("country") or "").strip() or None,
            publish_at=_d_mon_yyyy(date_m.group("v")) if date_m else None,
            description=desc_text,
        )


def _recruit_type(title: str, job_type: str = "") -> str:
    blob = f"{title} {job_type}".lower()
    if re.search(r"\bintern(ship)?\b|\btrainee\b|\bapprentice\b|实习", blob):
        return "intern"
    if re.search(r"\bgraduate\b|\bcampus\b|校园|应届|管培", blob):
        return "campus"
    return "social"


def _global_cities(city: str) -> list[str]:
    """版式 B 的城市是英文（`Kuala Lumpur` / `Shanghai`）。

    先试英→中映射；映射不到就保留原文 —— 海外城市名宁可给英文，也不能丢。
    """
    if not city:
        return []
    zh = city_from_english(city)
    if zh:
        return [zh]
    return cities_from_text(city) or [city]
