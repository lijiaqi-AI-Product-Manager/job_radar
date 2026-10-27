"""北森招聘门户（新版，{tenant}.zhiye.com）。平台型：一个适配器服务所有新版门户租户。
侦察：docs/recon/beisen.md。旧版服务端渲染门户（如 smics）不走此适配器。

source.params:
  tenant: 子域名，如 "fosunpharma"
  host: 白标域名（可选）。北森支持公司把自己的域名 CNAME 到门户，接口原样挂在白标域上：
        `https://zhaopin.joyoung.com/api/Jobad/GetJobAdPageList` 直接回 `{"Code":200,"Count":51}`。
        这类门户**猜不到 tenant**（`joyoung.zhiye.com` 是 302 到 /404），只能靠官网反查拿到域名，
        所以配 host 时 tenant 只用于 source_job_id 前缀与 URL 拼装，请求一律走 host。
  页尺寸/详情页走 portal（social 默认），详见 normalize。
  page_size: 每页条数，默认 100（录 fixtures 时用小值）

**`DisplayFields` 是拿城市和发布日期的唯一开关**（2026-10-26 实测）。
不带这个字段时服务端只回 `LocNames: []`、`PostDate: "0001-01-01T00:00:00"` ——
看起来像「平台没有这些数据」，其实是**没要**。带上之后同一批接口立刻返回
`['安徽省·合肥市','北京市']` 和真实发布时间：
长鑫存储 2026 条、星巴克 18454 条、我爱我家 28892 条、奇瑞 5776 条全部从 0% 变 100%。
"""

import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, cities_from_title, date_only, grad_year_from_text

# `{host}` 既可能是 `xxx.zhiye.com`，也可能是白标域名 —— 两个模板都只用 host，不再拼后缀
LIST_URL = "https://{host}/api/Jobad/GetJobAdPageList"
DETAIL_URL = "https://{host}/{portal}/detail?jobAdId={id}"
PAGE_SIZE = 100
# 不传 `DisplayFields` 时服务端只回标题和 JD，城市与日期字段全是空壳（见模块注释）。
# 这份清单是从门户前端真实请求体里抄的（`/campus/jobs` 列表页），不是我猜的字段名：
# 传一个服务端不认识的字段会整条 500，所以只写实测能回数的这几个。
DISPLAY_FIELDS = ["Category", "LocId", "PostDate", "EndTime", "Degree", "ClassificationOne", "LocNames"]
# `2222-02-02` 是北森「长期有效」的哨兵值，`0001-01-01` 是「未填」。
# 两个都不是真实截止日，落库会被用户当成「还有 200 年可投」。
SENTINEL_DATES = {"2222-02-02", "0001-01-01"}
# 地点串形如 `安徽省·合肥市`（省·市，中间是间隔号 U+00B7），也可能只到省或只到区县。
LOC_SEP = re.compile(r"[·・/、,，]")
# 省级 / 特别行政区后缀。只用来剥「没有市级信息」的那一段，不影响「合肥市」这种真城市名。
PROVINCE_SUFFIX = ("特别行政区", "维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "省")
# 省级行政区全名（用于识别「`LocNames` 只给到省」的情况）。
# 实测北森自己的门户 `beisen.zhiye.com`：`LocNames: ["湖北省"]`、`["福建省"]`、`["北京"]`，
# 标题写的是「（华中战区/武汉）」「（华南战区/厦门）」。省级名字是**大区**，不是办公城市——
# 当成城市落库的话，用户搜「武汉」搜不到这批岗，搜「湖北」又会搜出一堆其实在长沙的岗。
PROVINCES = frozenset("""
北京 上海 天津 重庆 河北 山西 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南
广东 海南 四川 贵州 云南 陕西 甘肃 青海 台湾
内蒙古 广西 西藏 宁夏 新疆 香港 澳门
""".split())
# 这四个既是一级行政区，本身也是城市名（「北京」就是工作城市），不能按省跳过。
_MUNICIPALITIES = frozenset("北京 上海 天津 重庆 香港 澳门".split())

# CategoryId 是北森门户的招聘类型。这个编号**不是平台级规范，而是租户自助配置的**，
# 所以每加一个编号都必须有实测岗位名做证据（见 docs/recon/beisen.md 第 5 节）。
RECRUIT_TYPE = {
    "1": "social",   # 优衣库「优衣库伙伴三亚大悦城」——正编门店岗
    "2": "campus",   # 「2027届…」「27届研发技术类」
    "3": "intern",   # 「…实习生」
    "4": "social",   # 优衣库「官网旗舰店担当」——正编非门店运营岗
    "5": "social",   # 第二个社招页面（专家/资深岗）
    "6": "intern",   # 优衣库「非全日制北京石景山万达」——兼职，归实习是现有枚举里最贴近的
    "7": "social",   # 与 4 同档：正编门店/运营岗的第二档
    "8": "social",   # 茶颜悦色「茶颜-门店全职-启东」
    "9": "intern",   # 「古德墨柠-学生用工-长沙」「门店运营学生用工」——学生用工即校内兼职
    "11": "social",  # 茶颜悦色「资产专员-CY-TZ-武汉」
    "12": "intern",  # 「主播学生用工-CY-DS-长沙」——学生用工，按用工性质归实习
    "13": "intern",  # 「门店运营学生用工」
    "14": "intern",  # 「茶颜-门店兼职-宜章县」
}
PORTAL = {"social": "social", "campus": "campus", "intern": "intern"}


@register
class BeisenAdapter(Adapter):
    id = "beisen"

    @property
    def tenant(self) -> str:
        return self.source.params["tenant"]

    @property
    def host(self) -> str:
        """请求用的主机：白标域名优先（见模块注释），否则 `{tenant}.zhiye.com`。"""
        return self.source.params.get("host") or f"{self.tenant}.zhiye.com"

    def fetch_raw(self) -> Iterator[dict]:
        if self.source.params.get("html_mode"):
            yield from self._fetch_html()
            return
        size = int(self.source.params.get("page_size", PAGE_SIZE))
        page = 0
        while True:
            text = self.request_text("POST", LIST_URL.format(host=self.host), json={
                "PageIndex": page, "PageSize": size, "KeyWords": "", "SpecialType": 0, "PortalId": "",
                "DisplayFields": DISPLAY_FIELDS,
            })
            if _is_api_404(text):
                # 新版门户（CmsPortal 6）把 `/api/Jobad/GetJobAdPageList` 整个下线了，
                # 回的是 HTML 的「Not Found」页（HTTP 200！），不是 JSON 也不是 404。
                # 这时只能走门户自己的服务端渲染列表 + 详情页（见 `_fetch_html`）。
                # 用 `request_text` 而不是 `request_json`，否则 `request_json` 会把
                # 「返回的不是 JSON」当成反爬直接抛错，整源失败。
                yield from self._fetch_html()
                return
            data = _loads(text)
            if data.get("Code") != 200:
                raise RuntimeError(f"beisen {self.tenant} code={data.get('Code')} {data.get('Message')}")
            items = data.get("Data") or []
            yield from items
            total = data.get("Count") or 0
            if not items or (page + 1) * size >= total:
                return
            if self.source.max_pages and page + 1 >= self.source.max_pages:
                return
            page += 1

    def _fetch_html(self) -> Iterator[dict]:
        """新版门户（`/alljob/?o=N` 服务端渲染）兜底抓取。

        2026-10-27 实测：`ctyun`（中国电信天翼云，73 岗）、`shougangfund`（首钢基金，53 岗）
        的 JSON 接口全部 404，但 `/alljob/?o=1` 直接出 `<table class="jobsTable">`，
        每行 `职位名称 / 职位类型 / 工作地点 / 发布时间`，分页是 `?o=1&PageIndex=2`。
        `/Campus`、`/social` 是门户导航链接，有内容时同样出这张表（`o` 与栏目无关，
        只是「全部职位」入口），所以先试 `o=1`，条目为 0 再试 `o=2`（另一套招聘类别分组）。

        详情页 `/zpdetail/{id}` 里：标题在 `div.xiangqingtitle`，
        「招聘类别/工作性质/招聘人数/发布时间/截止时间」在 `li.ntitle` + `li.nvalue` 配对里，
        城市与 JD 在 `div.xiangqingtext`（`<p>工作地点：</p>` 下一段是城市）。
        """
        p = self.source.params
        columns = p.get("html_columns") or ["/alljob/?o=1", "/alljob/?o=2"]
        seen: set[str] = set()
        got_any = False
        for col in columns:
            page = 1
            while True:
                url = f"https://{self.host}{col}"
                if page > 1:
                    url += ("&" if "?" in col else "?") + f"PageIndex={page}"
                html = self.request_text("GET", url)
                rows = _parse_html_list(html)
                fresh = [r for r in rows if r["id"] not in seen]
                for r in fresh:
                    seen.add(r["id"])
                got_any = got_any or bool(fresh)
                for r in fresh:
                    detail = {}
                    try:
                        detail = _parse_html_detail(
                            self.request_text("GET", f"https://{self.host}/zpdetail/{r['id']}?o=1"))
                    except Exception:  # noqa: BLE001 — 单条详情失败不影响整源，JD 留空
                        detail = {}
                    yield {**r, "detail": detail}
                last = max([int(x) for x in re.findall(r"PageIndex=(\d+)", html)] or [1])
                if not rows or page >= last:
                    break
                if self.source.max_pages and page >= self.source.max_pages:
                    break
                page += 1
        if not got_any:
            # 门户确实是空的（`/alljob/` 表里一条都没有）：照常返回空，让 ingest 的
            # 「空结果保护」去决定要不要拒收，而不是在这里伪装成有数据。
            return

    def _normalize_html(self, raw: dict) -> Job:
        """新版门户（`_fetch_html`）的记录 → Job。字段来源见 `_fetch_html` 的注释。"""
        detail = raw.get("detail") or {}
        meta = detail.get("meta") or {}
        title = (detail.get("title") or raw.get("title") or "").strip()
        if not title or not raw.get("id"):
            raise SkipRecord
        recruit_type = _html_recruit_type(raw.get("kind") or meta.get("招聘类别") or "", title)
        if recruit_type not in self.source.recruit_types:
            raise SkipRecord
        city = _strip_tags(detail.get("工作地点") or "") or (raw.get("loc") or "")
        cities = cities_of_locstr(city)
        if not cities:
            cities = cities_from_title(title)
        duty = _clean_text(detail.get("工作职责") or detail.get("岗位职责"))
        req = _clean_text(detail.get("任职资格") or detail.get("任职要求") or detail.get("岗位要求"))
        return Job(
            source_id=self.source.id,
            source_job_id=raw["id"],
            company=self.source.company,
            url=f"https://{self.host}/zpdetail/{raw['id']}?o=1",
            title=title,
            recruit_type=recruit_type,
            grad_year=grad_year_from_text(title) if recruit_type != "social" else None,
            batch=batch_from_text(title) if recruit_type == "campus" else None,
            cities=cities,
            degree_min=None,
            description=duty,
            requirements=req,
            # 列表页的「发布时间」列是真实日期（`2022-10-14`）；详情页 `发布时间` 同名同值。
            # 截止时间常是 `&nbsp;`（未填），`_not_sentinel` 会把空值变成 None。
            publish_at=_not_sentinel(raw.get("date")) or _not_sentinel(meta.get("发布时间")),
            apply_end=_not_sentinel(meta.get("截止时间")),
        )

    def normalize(self, raw: dict) -> Job:
        if "detail" in raw:
            return self._normalize_html(raw)
        recruit_type = RECRUIT_TYPE.get(str(raw.get("CategoryId")))
        if not raw.get("Id") or not raw.get("JobAdName") or recruit_type is None:
            raise SkipRecord
        if recruit_type not in self.source.recruit_types:
            raise SkipRecord
        title = raw["JobAdName"].strip()
        cities = cities_of(raw.get("LocNames"))
        if not cities:
            # `LocNames` 空但有标题写了地点时，退到标题抽取。
            # 实测药明合联 179/634 条 `LocNames` 为空，其中 86 条标题明写「-苏州」「-武汉」「-南京」，
            # 而门户页面上这些岗位的地点列**是显示出来的**（「有机合成高级研究员-武汉(J21485) … 武汉」）
            # ——说明数据在，只是没走 `LocNames` 这条路。
            #
            # 只在 `LocNames` 为空时用：字段有值时它是权威，标题是补充，不能反过来覆盖。
            # 抽取器本身带三道闸门（城市必须在片段开头 / 要有岗位类词 / 排除专有名词反例），
            # 「上海大众汽车工程师」「北京大学合作项目专员」都不会命中。
            cities = cities_from_title(title)
        # 日期：列表接口本来就给了 `PostDate` / `EndTime`，之前整个被丢掉了（全项目 publish_at
        # 只有 1.2% 就有一份是这个原因）。`0001-01-01T00:00:00` 是「未填」哨兵，
        # `date_only()` 已经会把它变成 None，不需要在这里再判一遍。
        #
        # 两个都有真值时才用 `PostDate`；只有一个真值时用 `PostDate` 的**值**做「同批」判断：
        # 北森同一租户同一批次的岗位 `PostDate` 是逐秒递增的，真正的「发布时间」在作业里
        # 往往只填在其中一个字段上。实测康弘药业：`PostDate` 全是哨兵，`EndTime` 是
        # 2025-12-27 / 2026-04-01 这种「批次维护日」，比「没有日期」有用得多。
        # 两个都是哨兵时退到 `ChangeDate`（最后修改时间）。它不是发布时间，所以**只在
        # 两个正字段都没有时才用**，而且拿到的往往是一整批岗位共享的同一个时间戳
        # （京东方、海信实测：同一次导入的全部岗位 `ChangeDate` 逐秒相同）。
        # 有它总比没有强：日历条目至少要能落在「这一批是什么时候挂出来的」附近。
        post_raw, end_raw = raw.get("PostDate"), raw.get("EndTime")
        publish_at = _not_sentinel(post_raw)
        apply_end = _not_sentinel(end_raw)
        if publish_at is None and apply_end is None:
            publish_at = date_only(raw.get("ChangeDate"))
        return Job(
            source_id=self.source.id,
            source_job_id=raw["Id"],
            company=self.source.company,
            url=DETAIL_URL.format(host=self.host, portal=PORTAL[recruit_type], id=raw["Id"]),
            title=title,
            recruit_type=recruit_type,
            grad_year=grad_year_from_text(title) if recruit_type != "social" else None,
            batch=batch_from_text(title) if recruit_type == "campus" else None,
            cities=cities,
            degree_min=raw.get("Degree") or None,
            # 有租户把 Duty/Require 填成占位符 `"1"`（2026-10-26 实测货拉拉 202/534 条）。
            # 那不是正文，落库只会让「JD 覆盖率 100%」变成假数字 —— 宁可当没有。
            description=_clean_text(raw.get("Duty")),
            requirements=_clean_text(raw.get("Require")),
            publish_at=publish_at,
            apply_end=apply_end,
        )


def _clean_text(value) -> str | None:
    """JD 字段清洗：太短的当没有。

    判据是「去掉空白后 < 10 个字符」——正常 JD 无论是中文还是英文都远超这个长度，
    而占位符（`1`、`无`、`-`、`N/A`）都在 10 以内。**不按长度猜内容**，只用来识别占位符。
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s if len(re.sub(r"\s+", "", s)) >= 10 else None


def _not_sentinel(value) -> str | None:
    """哨兵日期一律当没有。

    `date_only()` 会把 `2100` 之后的年份直接判为不可信，本来就能挡住 `2222-02-02`；
    这里再显式挡一次，是因为哨兵的具体值将来可能变（`2222-02-02` 是 2026-10-26 实测的），
    而「长期有效」被当成真实截止日会直接误导投递决定——值得多一层。
    """
    if not isinstance(value, str):
        return date_only(value)
    if value.strip()[:10] in SENTINEL_DATES:
        return None
    return date_only(value)


def _is_api_404(text: str) -> bool:
    """北森老接口下线时回的是 HTML「Not Found」页，且 **HTTP 状态码是 200**。"""
    head = (text or "").lstrip()[:400].lower()
    return head.startswith("<!doctype") or head.startswith("<html")


def _loads(text: str) -> dict:
    import json
    try:
        return json.loads(text)
    except ValueError as e:
        raise RuntimeError(f"beisen 列表接口返回的不是 JSON：{text[:120]!r}") from e


# 两种行结构都见过（2026-10-27 实测）：
#  - shougangfund：`<td><a title="…" href="/zpdetail/1?o=1">…</a></td><td title=""></td><td title="北京市">…</td><td>2022-10-14</td>`
#  - ctyun（同一模板的 thead/tbody 版本）：每个 `<td>` 都带 `class="tableleft joblsttitle"`，
#    标题里还多一个 `jobAdId` 属性。所以 `<td>` 的属性部分一律用 `[^>]*` 吃掉，不写死。
_ROW_RE = re.compile(
    r'<a title="(?P<title>[^"]*)"[^>]*href="/zpdetail/(?P<id>\d+)\?o=\d+"[^>]*>.*?</a>\s*</td>'
    r'\s*<td[^>]*title="(?P<kind>[^"]*)"[^>]*>.*?</td>'
    r'\s*<td[^>]*title="(?P<loc>[^"]*)"[^>]*>.*?</td>'
    r'\s*<td[^>]*>\s*(?P<date>[^<]*?)\s*</td>', re.S)


def _parse_html_list(html: str) -> list[dict]:
    """`<table class="jobsTable">` 的每一行 → `{id, title, kind, loc, date}`。

    行结构（2026-10-27 实测 shougangfund / ctyun）：
    `<td><a title="投资拓展经理" href="/zpdetail/270512937?o=1">…</a></td>`
    + `<td title=""></td>`（职位类型，多数租户是空）
    + `<td title="北京市">北京市</td>` + `<td>2022-10-14</td>`。
    """
    out: list[dict] = []
    for m in _ROW_RE.finditer(html or ""):
        out.append({
            "id": m.group("id"),
            "title": _unescape(m.group("title")).strip(),
            "kind": _unescape(m.group("kind")).strip(),
            "loc": _unescape(m.group("loc")).strip(),
            "date": _unescape(m.group("date")).strip(),
        })
    return out


def _unescape(s: str) -> str:
    import html as _html
    return _html.unescape(s or "")


_NTITLE_RE = re.compile(
    r'<li class="ntitle[^"]*"[^>]*>\s*([^<]{0,20}?)\s*[：:]\s*</li>\s*'
    r'<li class="nvalue"[^>]*>([\s\S]{0,200}?)</li>')


def _parse_html_detail(html: str) -> dict:
    """详情页 → `{title, meta{…}, city, duty, require}`。取不到的字段一律缺省，不猜。"""
    out: dict = {}
    m = re.search(r'<div class="xiangqingtitle">\s*<span>([\s\S]*?)</span>', html or "")
    if m:
        out["title"] = _strip_tags(m.group(1))
    meta = {}
    for k, v in _NTITLE_RE.findall(html or ""):
        meta[_strip_tags(k)] = _strip_tags(v)
    out["meta"] = meta
    # `xiangqingtext` 里是「<p>小标题：</p><p>内容</p>」的成对结构
    body = ""
    i = (html or "").find('class="xiangqingtext"')
    if i > 0:
        body = html[i:]
        j = body.find("现在申请")
        if j > 0:
            body = body[:j]
    blocks = re.findall(r"<p[^>]*>([\s\S]*?)</p>", body)
    cur = None
    for b in blocks:
        t = _strip_tags(b)
        if not t:
            continue
        if t.endswith(("：", ":")) and len(t) <= 12:
            cur = t[:-1]
            out.setdefault(cur, "")
            continue
        if cur:
            out[cur] = (out[cur] + "\n" + t).strip()
    return out


def _strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _unescape(s).replace("\xa0", " ")
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def _html_recruit_type(kind: str, title: str) -> str:
    """职位类型列 → 招聘类型。

    新版门户的「职位类型」列**不是**校招/社招（多数租户是空的，ctyun 填的是
    「研发/产品/运营/销售/职能」这类职能），所以只在字面明确时采用，其余按社招。
    猜测校招会把社招岗混进校招日历，比漏判更糟。
    """
    s = f"{kind} {title}"
    if "实习" in s:
        return "intern"
    if re.search(r"(校园|校招|应届|管培|储备干部|培训生|23|24|25|26|27|28)届", s):
        return "campus"
    return "social"


def cities_of_locstr(loc: str) -> list[str]:
    """新版门户的地点串 → 中文城市名。

    `北京市` / `江苏省-无锡市` / `四川省-成都市` / `全国` / `福建省`（只有省）。
    分隔符是裸 `-`，和 `LocNames` 的 `·` 不同，所以不能直接复用 `cities_of`。
    只有省级且非直辖市时返回空（同 `cities_of` 的理由）。
    """
    if not loc:
        return []
    parts = [p.strip() for p in re.split(r"[·・/、,，\-]", loc) if p.strip()]
    out: list[str] = []
    for p in parts:
        if p in ("全国", "不限", "全球"):
            continue
        city = p
        for suffix in ("市", *PROVINCE_SUFFIX):
            if city.endswith(suffix) and len(city) > len(suffix):
                city = city[: -len(suffix)]
                break
        if city in PROVINCES and city not in _MUNICIPALITIES:
            continue
        if city and city not in out:
            out.append(city)
    return out


def cities_of(loc_names) -> list[str]:
    """`LocNames` 里的地点串 → 中文城市名列表。

    真实形态是 `安徽省·合肥市`（省·市，间隔号）或 `广东省·广州市·花都区`（省·市·区），
    取**市级**那段；只有省没有市时（直辖市常写成 `上海市`）取省名去掉后缀。
    不能整串塞进 `cities`——用户搜「合肥」要能命中，搜「安徽省·合肥市」谁也搜不出来。

    **只给到省、且这个省不是直辖市/特别行政区时，返回空**，交给 `cities_from_title()` 兜底。
    `湖北省` 不是一个城市：直接落库会让搜「武汉」的人漏掉这批岗，搜「湖北」的人看到一堆
    其实在长沙的岗。宁可从标题取（`LocNames` 为空时才会走到那条路），也不要给省级名。
    """
    if not loc_names:
        return []
    out: list[str] = []
    for raw in loc_names:
        if not isinstance(raw, str):
            continue
        parts = [p.strip() for p in LOC_SEP.split(raw) if p.strip()]
        if not parts:
            continue
        # 取最后一个「以 市/自治州/地区/盟 结尾」的段；取不到就退第一个
        city = next((p for p in reversed(parts) if p.endswith(("市", "自治州", "地区", "盟"))), None)
        if city is None:
            city = parts[0]
        for suffix in ("市", *PROVINCE_SUFFIX):
            if city.endswith(suffix) and len(city) > len(suffix):
                city = city[: -len(suffix)]
                break
        # 「湖北省」「福建省」这类是省，不是办公城市；「北京」「上海」既是直辖市也是城市，保留。
        # 跳过后上层会退到标题抽取（`cities_from_title`），标题里通常写着「（华中战区/武汉）」。
        if city in PROVINCES and city not in _MUNICIPALITIES:
            continue
        if city and city not in out:
            out.append(city)
    return out
