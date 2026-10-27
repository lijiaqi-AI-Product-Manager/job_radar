"""Radancy / TalentBrew 招聘站（`careers.<公司>.com`，欧洲跨国企业常用）。

侦察：docs/recon/radancy.md。典型域名：`careers.loreal.com`、`jobs.sanofi.cn`、`careers.unilever.com`。
只读公开 HTML，无需登录、无签名、无验证码。

**同一平台存在两种卡片形态**，适配器按抓到哪张就用哪张（2026-10-26 实测）：

  形态 A（欧莱雅 / 联合利华，`<a class="…job-link">`）：
      <a class="job-link" href="…" data-job-id="123">
        <h3>岗位名</h3><span class="job-location">Shanghai, China Mainland</span>
  形态 B（赛诺菲，`#search-results-list` 里普通 `<a>`）：
      <ul><li><a href="/工作/北京/…/3036/46350248512" data-job-id="46350248512">
        <h2>岗位名</h2><span class="job-location"><strong>地点: </strong>北京, 中国</span>

  两种都以 `data-job-id` 为主键，都带 `job-location` 类，所以正则只锚这两点、不锚 class 名。

列表 URL：
  A: GET {base}/{lang}/search-jobs/{country}      分页 `?p=N`（`?page=` 与 `/N` 都无效）
  B: GET {base}/search-jobs                       默认就是全中国（data-total-results 971），`?p=N` 同样有效
  每页 15 条，分页边界写在 `data-total-pages` / `data-records-per-page`

详情：GET {base}{href}，正文在 `id="anchor-job-description"`（形态 A）或 `id="job-description"`（形态 B）。

日期：Radancy 的「已发布」是前端相对文案（"Posted 3 days ago"），页面里没有绝对日期，
所以 publish_at / apply_end 一律留空，不猜。

source.params:
  base: 站点根，如 "https://careers.loreal.com"
  lang: 语言段，默认 "en"（形态 B 的站点没有语言段，配 lang: "" 即可）
  country: 列表页的国家段，如 "China"（形态 B 不用，配 country: ""）
  page_size: 每页条数（站点固定 15，仅用于计算翻页上限），默认 15
  fetch_detail: 是否进详情页取 JD，默认 True
"""

import html
import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import cities_from_text, city_from_english, grad_year_from_text

DEFAULT_PAGE_SIZE = 15  # 站点固定每页 15 条（分页由 data-total-pages 决定）

# 卡片：<a … data-job-id="123"> <h2|h3>标题</h2|h3> … <span class="job-location">地点</span> … </a>
# 不锚 `job-link` class —— 赛诺菲的卡片就是裸 <a>。用 data-job-id + h1..h3 + job-location 三点定位。
# 中间可能先出现 `<div class="brand-logo-wrapper"><img …></div>` 再是标题（阿斯利康），
# 所以 `>\s*<h` 不能写死，要用 `>` + 最多几个非 <a 标签的任意内容再找 `<h1..h3>`。
CARD = re.compile(
    r'<a[^>]*data-job-id="(?P<id>\d+)"[^>]*>(?:(?!</a>).)*?<h(?P<h>[1-3])[^>]*>(?P<title>.*?)</h(?P=h)>'
    r'(?P<rest>.*?)</a>',
    re.S,
)
HREF = re.compile(r'href="(?P<href>[^"]+)"')
LOC = re.compile(r'class="[^"]*job-location[^"]*"[^>]*>(?P<loc>.*?)</span>', re.S)
# 形态 B 的 <span class="job-location"><strong>地点: </strong>北京, 中国</span>，要剥掉「地点: 」前缀
LOC_LABEL = re.compile(r"^\s*(?:地点|Location|工作地点)\s*[:：]\s*", re.I)
TOTAL_PAGES = re.compile(r'data-total-pages="(\d+)"')
TOTAL_RESULTS = re.compile(r'data-total-results="(\d+)"')
# 正文容器三种：
#   形态 A  <section id="anchor-job-description">…</section>（欧莱雅）
#   形态 B  <div class="job-description section7-details">…<div class="ats-description">…</div></div>（赛诺菲）
DESC_ANCHOR = re.compile(r'id="(?:anchor-job-description|job-description)"[^>]*>(?P<body>.*?)</section>', re.S)
# 收尾不能用 `</div>\s*</div>`：正文里嵌套几十个 <div>，非贪婪会在第 2 个就停
# （2026-10-26 实测正文只剩 200 字）。改用「一直取到 <style> / <footer> / 下一个 section 之前」，
# 由 _text() 兜住多取的标签。
DESC_DIV = re.compile(r'class="job-description[^"]*section7-details"[^>]*>(?P<body>.*?)'
                      r'(?=<style|</body>|<footer|<section)', re.S)
# 正文本体单独抽一层，形态 B/D 共用：优先 ats-description，没有就整块
ATS_INNER = re.compile(r'<div class="ats-description"[^>]*>(?P<body>.*)', re.S)
# 形态 C（欧莱雅）：<div class="job-description" …><div class="ats-description">…</div>
# 这个站点**没有** id="anchor-job-description"，也没有 section7-details，只有裸的 job-description。
DESC_ATS = re.compile(r'class="job-description"[^>]*>\s*<div class="ats-description"[^>]*>(?P<body>.*?)</div>', re.S)
# 形态 D（阿斯利康 job-search.astrazeneca.cn）：
#   <section class="job-description" …> <div class="details-and-apply-button"> 地点/职位ID/发布日期 </div>
#     <div class="ats-description">正文…</div>
#   </section>
# 与形态 C 的差别：正文前面夹了一整个工具栏 div，`\s*` 跨不过去。
# 所以按 `<section class="job-description"` 起点 + 「后续第一个 ats-description」定位，
# 收尾与 DESC_DIV 一样取到下一个 section 之前（正文里嵌套 <div> 太多）。
DESC_SECTION = re.compile(r'<section class="job-description"[^>]*>(?P<body>.*?)(?=<section|</body>|<footer)', re.S)
# 赛诺菲详情页有**绝对日期**，比形态 A 的 "Posted 3 days ago" 好得多：
#   <span class="job-date job-info"><b>发布于 &nbsp;</b> Oct. 26, 2026</span>
#   <span class="job-end-date job-info"><b>申请截止于 &nbsp;</b> Nov. 30, 2026</span>
PUB_DATE = re.compile(r'class="job-date[^"]*"[^>]*>(?P<v>.*?)</span>', re.S)
END_DATE = re.compile(r'class="job-end-date[^"]*"[^>]*>(?P<v>.*?)</span>', re.S)
JOB_TYPE = re.compile(r'class="job-type[^"]*"[^>]*>(?P<v>.*?)</span>', re.S)
TRAILING_DATE = re.compile(
    r"(?P<d>[A-Z][a-z]{2}\.?\s+\d{1,2},\s*\d{4}"   # Oct. 26, 2026（赛诺菲）
    r"|\d{1,2}月\.?\s*\d{1,2},\s*\d{4}"               # 10月. 25, 2026（赛诺菲，个别岗位本地化成中文月份）
    r"|\d{4}-\d{2}-\d{2}"                             # 2026-10-26
    r"|\d{1,2}/\d{1,2}/\d{4})\s*$"                    # 07/07/2026（阿斯利康，MM/DD/YYYY）
)
TAG = re.compile(r"<[^>]+>")
# 省级行政区（不要出现在「城市」字段里；只剩省时才保留）
_PROVINCES = frozenset("""
河北 山西 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 海南 四川 贵州 云南
陕西 甘肃 青海 台湾 内蒙古 广西 西藏 宁夏 新疆
""".split())


def _is_province(name: str) -> bool:
    return name in _PROVINCES


# 城邦：既是国家也是城市，日历的「城市」字段要它们（2026-10-26 实测赛诺菲有新加坡岗位）
_CITY_STATES = frozenset({"新加坡", "中国香港", "中国澳门", "香港", "澳门", "Singapore"})


# 出现在 job-location 里但**不是**城市的词（国家、大区、占位词）
# 列表卡片写「Multiple locations」时，URL 路径里的城市段（`/工作/上海/slug/…`）才是真值。
# 路径段是百分号编码的 UTF-8，要先 unquote 再判断。
_CITY_IN_PATH = re.compile(r"/(?:工作|job)/(?P<city>[^/]+)/", re.I)


def _city_from_url(url: str) -> list[str]:
    """URL 路径里的城市段。

    `_cities()` 只认城市词典里的名字，海外小城（`verna`=保加利亚韦尔纳、`jakarta`）会返回空。
    这时退回**原文**：日历的「城市」字段宁可给一个英文地名，也不能因为词典不全就整条丢掉
    —— 用户看到「Verna」能自己去查，看到空就什么都不知道了（2026-10-26 实测赛诺菲 33 条被丢）。
    但「中国」「全国」这类不含地点的段仍然要被过滤掉。
    """
    from urllib.parse import unquote

    m = _CITY_IN_PATH.search(unquote(url))
    if not m:
        return []
    raw = m.group("city").strip()
    return _cities(raw) or ([raw] if raw and raw not in _NOT_CITIES and len(raw) > 1 else [])


# 中文国家/大区名：`cities_from_text` 不认它们是国名，会原样返回，必须显式挡掉
_COUNTRY_ZH = frozenset("""
中国 中国大陆 中国内地 全国 全球 亚太 亚太区 亚洲 欧洲 美洲 北美 非洲 中东
印度 日本 韩国 马来西亚 泰国 越南 印度尼西亚 菲律宾 澳大利亚 新西兰 巴西 墨西哥
美国 加拿大 英国 法国 德国 意大利 西班牙 荷兰 比利时 瑞士 瑞典 丹麦 挪威 芬兰 波兰
爱尔兰 葡萄牙 奥地利 希腊 土耳其 俄罗斯 以色列 保加利亚 埃及 南非 阿根廷 智利 哥伦比亚
""".split())

_NOT_CITIES = frozenset("""
中国 中国大陆 中国内地 全国 全球 亚太 亚太区 亚洲 欧洲 美洲 北美
China "China Mainland" Mainland China APAC Global
""".split())

# 列表页的**占位**地点串：不是地名，遇到就得去 URL 路径里找真值（2026-10-26 实测阿斯利康 29 条）
_PLACEHOLDERS = frozenset({"multiple locations", "various locations", "multiple", "各种地点"})


def _text(fragment: str | None) -> str | None:
    if not fragment:
        return None
    s = html.unescape(TAG.sub(" ", fragment))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    return s or None


def _clean_location(location: str | None) -> str | None:
    """剥掉「地点: 」这类标签前缀，剩下的才是地名串。"""
    if not location:
        return None
    return LOC_LABEL.sub("", location).strip() or None


_EN_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _en_date(fragment: str | None) -> str | None:
    """从 `<b>发布于 </b> Oct. 26, 2026` 里取出 `2026-10-26`。

    形态 A（欧莱雅）只有 "Posted 3 days ago" 这种相对文案，所以这份解析只服务形态 B；
    解析不出来就返回 None —— 宁可不填，也不猜一个日期。
    """
    if not fragment:
        return None
    s = _text(fragment) or ""
    m = TRAILING_DATE.search(s)
    if not m:
        return None
    raw = m.group("d")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    # 形态 D（阿斯利康）的日期是 `07/07/2026`（MM/DD/YYYY，站点 DisplayJobDateFormat）。
    # 不能靠猜：只有当两段数都 ≤12 时歧义才需要，这里按站点声明的 MM/DD 解读。
    mm_us = re.fullmatch(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})", raw)
    if mm_us:
        return f"{int(mm_us.group('y')):04d}-{int(mm_us.group('m')):02d}-{int(mm_us.group('d')):02d}"
    # 中文月份：`10月. 25, 2026`（赛诺菲个别岗位把 MMM. 本地化成了「10月.」，
    # 站点的 DisplayJobDateFormat 仍是 `MMM. dd, yyyy`）。2026-10-26 实测 75 个岗位里有 1 个。
    zh_cn = re.fullmatch(r"(?P<m>\d{1,2})月\.?\s*(?P<d>\d{1,2}),\s*(?P<y>\d{4})", raw)
    if zh_cn:
        mon, day = int(zh_cn.group("m")), int(zh_cn.group("d"))
        if not (1 <= mon <= 12 and 1 <= day <= 31):
            return None
        return f"{int(zh_cn.group('y')):04d}-{mon:02d}-{day:02d}"
    mm = re.match(r"(?P<mon>[A-Za-z]{3})\.?\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})", raw)
    if not mm:
        return None
    mon = _EN_MONTHS.get(mm.group("mon").lower())
    if not mon:
        return None
    return f"{int(mm.group('year')):04d}-{mon:02d}-{int(mm.group('day')):02d}"


def _cities(location: str | None) -> list[str]:
    """Radancy 的地点串是英文且带行政区后缀：
    "Shanghai, Shanghai Municipality, China Mainland" / "Guangzhou, Guangdong, China Mainland"。

    只认 CITY_EN 里能映射到中文的地名，**不要**用 cities_from_text —— 它按中文"市/省"规则切分，
    遇到英文串会把 "Shanghai"、"Shanghai Municipality"、"China Mainland" 当成三个城市收进去
    （2026-10-26 实测：城市字段被污染成英文地名）。

    形态 B（赛诺菲）的地点串是**中文**（"北京, 中国"），`city_from_english("北京")` 返回 None
    （它只做英→中，不做中→中），所以中文分段要交给 `cities_from_text`。
    """
    if not location:
        return []
    # 形态 D（阿斯利康）的地点串是「省 市」用空格分隔：「上海 上海」「江苏 无锡」。
    # 不先按空格拆开，`cities_from_text("上海 上海")` 会原样返回「上海 上海」。
    # 只在**没有逗号**时才按空格拆，避免把英文 "China Mainland" 拆成两段。
    if "," not in location and "，" not in location and re.search(r"[\u4e00-\u9fff]", location):
        location = re.sub(r"\s+", ",", location.strip())
    out: list[str] = []
    parts = [x.strip() for x in re.split(r"[,，/、]", location)]
    parts = [x for x in parts if x]
    _first_part = parts[0] if parts else None
    for part in parts:
        if not part:
            continue
        # 占位词先挡掉：站点列表写「Multiple locations」时，真值只在 URL 路径里。
        # `_cities()` 自己不能决定"该不该去 URL 兜底"，所以这里直接忽略，
        # 让调用方的 `_cities(...) or _city_from_url(...)` 生效（2026-10-26 实测阿斯利康 29 条）。
        if part.lower() in _PLACEHOLDERS:
            continue
        # 上一轮的 found 不能带过来：小写地名（"verna"）下面只命中最后一条分支，
        # 但有分支不命中时沿用旧值会出错（2026-10-26 实测 UnboundLocalError）。每轮重置。
        found: list[str] = []
        zh = city_from_english(part)
        if zh:
            found = [zh]
        elif re.search(r"[\u4e00-\u9fff]", part):
            # 中文串按「市/省/区」规则切。`cities_from_text` 对「印度」会原样返回，
            # 所以国家名要在这里就挡掉，不能靠后面那道 `_NOT_CITIES`——它挡不住
            # `cities_from_text` 产出的同名字符串（2026-10-26 实测「海得拉巴, 印度」→ ['海得拉巴','印度']）。
            found = cities_from_text(part) if part not in _COUNTRY_ZH else []
        elif part in _CITY_STATES or (part.isascii() and part[:1].isupper() and len(part) > 2):
            # 海外地名：城市词典只收中国城市（`city_from_english` 是英→中映射表），
            # 保加利亚的 Verna、印尼的 Jakarta 全查不到。日历宁可给英文原名也不留空，
            # 但要避开 "Bulgaria" / "Indonesia" 这种国名 —— 用「第一个分段」规则：
            # 英文地名串的第一个分段就是城市（"Jakarta, Jakarta …, Indonesia" / "Verna, Bulgaria"）。
            found = [part] if part is _first_part else []
        elif part.isascii() and len(part) > 2:
            # 全小写的英文地名段（URL 兜底路径传进来的 `verna`）走同一条「首段即城市」规则
            found = [part] if part is _first_part else []
        for c in found:
            # 国名/大区名不是城市。赛诺菲的地点串是「北京, 中国」，不加这层过滤会把「中国」
            # 当成一个城市收进去（2026-10-26 实测 15 条岗位里有 15 条带「中国」）。
            if c not in out and c not in _NOT_CITIES:
                out.append(c)
    # 「省 市」串会同时切出省和市（江苏, 无锡）。日历的「城市」字段要城市，
    # 有市就别留省 —— 但只剩省（没有市）时得留着，那是这条岗位唯一的地区信息。
    cities = [c for c in out if not _is_province(c)] or out
    return cities


def recruit_type_of(title: str, job_type: str = "") -> str:
    """默认社招，标题或 `job-type` 里明写实习/校招才改。

    赛诺菲的 `job-type` 值是 "Apprentice/Intern (Fixed Term)"，欧莱雅没有这个字段；
    两边都以标题为主，job-type 只做补充。
    """
    blob = f"{title} {job_type}".lower()
    if re.search(r"\bintern(ship)?\b|\btrainee\b|\bapprentice\b|实习", blob):
        return "intern"
    if re.search(r"\bgraduate\b|\bcampus\b|\bnew college\b|校园|应届", blob):
        return "campus"
    return "social"


@register
class RadancyAdapter(Adapter):
    id = "radancy"

    def _base(self) -> str:
        return self.source.params["base"].rstrip("/")

    def _list_url(self, page: int) -> str:
        """形态 A 与形态 B 的差别只在 url 前缀；分页参数都是 `?p=N`。

        `path` 是给「robots.txt 禁了 /search-jobs」的站点用的（欧莱雅、联合利华都禁了）。
        这类站点有等价的公开着陆页：`/en/location/china-mainland-jobs/3456/1814991/2`
        —— 那个尾数 `2` 就是页号（不是 `?p=N`），所以 path 里用 `{page}` 占位。
        """
        p = self.source.params
        url = f"{self._base()}/{p['path'].strip('/')}" if p.get("path") else self._search_url()
        # path 模式：page 直接塞进路径；首页时把 `/1` 去掉更像人点进去的样子
        if p.get("path"):
            return url.format(page=page)
        return f"{url}?p={page}" if page > 1 else url

    def _search_url(self) -> str:
        p = self.source.params
        lang = (p.get("lang") or "").strip("/")
        country = (p.get("country") or "").strip("/")
        parts = [x for x in (lang, "search-jobs", country) if x]
        return f"{self._base()}/{'/'.join(parts)}"

    def fetch_raw(self) -> Iterator[dict]:
        p = self.source.params
        fetch_detail = bool(p.get("fetch_detail", True))
        page = 1
        seen: set[str] = set()
        total_pages: int | None = None
        while True:
            body = self.request_text("GET", self._list_url(page))
            cards = list(CARD.finditer(body))
            if total_pages is None:
                m = TOTAL_PAGES.search(body)
                total_pages = int(m.group(1)) if m else 0
            # 自检：分页参数失效时站点会一直返回第 1 页，整页都是见过的 id 就停
            fresh = [c for c in cards if c.group("id") not in seen]
            if not fresh:
                return
            for card in fresh:
                jid = card.group("id")
                seen.add(jid)
                href_m = HREF.search(card.group(0))
                if not href_m:
                    continue
                detail = ""
                if fetch_detail:
                    try:
                        detail = self.request_text("GET", self._base() + href_m.group("href"))
                    except Exception:  # noqa: BLE001 — 详情失败只是缺正文，不影响这条岗位入库
                        detail = ""
                loc = LOC.search(card.group("rest"))
                yield {
                    "id": jid,
                    "href": href_m.group("href"),
                    "title": _text(card.group("title")),
                    "location": _clean_location(_text(loc.group("loc")) if loc else None),
                    "detail": detail,
                }
            if total_pages and page >= total_pages:
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def normalize(self, raw: dict) -> Job:
        title = (raw.get("title") or "").strip()
        if not title or not raw.get("id"):
            raise SkipRecord
        detail = raw.get("detail") or ""
        m = (DESC_ANCHOR.search(detail) or DESC_DIV.search(detail)
             or DESC_ATS.search(detail) or DESC_SECTION.search(detail))
        body = m.group("body") if m else None
        if body:
            inner = ATS_INNER.search(body)
            if inner:
                body = inner.group("body")
        desc = _text(body) if body else None
        pub = PUB_DATE.search(detail)
        end = END_DATE.search(detail)
        jtype = JOB_TYPE.search(detail)
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw["id"]),
            company=self.source.company,
            url=self._base() + raw["href"],
            title=title,
            recruit_type=recruit_type_of(title, jtype.group("v") if jtype else ""),
            grad_year=grad_year_from_text(title),
            # 列表地点为空或「Multiple locations」时，URL 路径里的城市段是唯一可信来源
            cities=_cities(raw.get("location")) or _city_from_url(raw.get("href") or ""),
            publish_at=_en_date(pub.group("v")) if pub else None,
            apply_end=_en_date(end.group("v")) if end else None,
            description=desc,
        )
