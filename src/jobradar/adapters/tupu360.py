"""Tupu360 招聘站（`jobs.<公司>.com.cn/<tenant>/position/index`）。常见于在华外企。

侦察：docs/recon/tupu360.md。只读公开服务端渲染的 HTML，无需登录、无签名、无验证码。

页面形态（2026-10-26 实测西门子 jobs.siemens.com.cn）：
  GET /{tenant}/position/index?recruitmentType=CAMPUSRECRUITMENT
    -> <div class="position-item" pid="…" recruitment="…">
         <h4 class="title"><span class="txt">岗位名</span></h4>
         <li class="ele"><span class="txt">工作地点：上海,北京</span></li>
         <li><span class="txt">职能类别：工程</span></li>
         <li><span class="txt">JobID:522053</span></li>
         <div class="time">发布于: 2026-10-08</div>
  分页：**不是** `?page=N`（实测 `&page=2` 与第 1 页 pid 完全相同）。真实机制在
  `position.index.js` 的 `pageTurn()` 里：

      POST /{tenant}/position/nextPageList
      data: recruitmentType=…&offset=(page-1)*max&max=15

  返回的是**整个 `#position-list` 片段**（含 `共41个职位` 与新的分页控件），
  所以第 1 页虽然走的是 GET index，后续页走 POST 也能复用同一套 `ITEM` 正则。
  增量加载（`pageLoadOptions`）用的是同一个 offset/max 语义，只是 max=10。

  `GET /{tenant}/position/positionTotal?recruitmentType=X` 返回 {"positionTotal": N}。

**同平台还有一种「列表式」卡片**（2026-10-26 实测 IQVIA / 英特尔 / 舍弗勒 / 埃森哲：
`careersite.tupu360.com/<tenant>` 而不是各家自己的域名）：

    <div class="position-item">                       <-- 注意没有 pid 属性
      <div class="ele e-title" title="岗位名"><a href='/iqvia/position/detail?positionId=…&recruitmentType=…'>岗位名</a></div>
      <div class="ele e-salary">业务</div>
      <div class="ele e-salary">职位类别</div>
      <div class="ele e-salary">辽宁省-大连</div>
      <div class="ele e-date">2026-10-15</div>
    </div>

顺序固定：e-title / 业务 / 职位类别 / 工作地点 / e-date。只有 e-title 有 title 属性，
所以**列名从 each 卡的 `.ele` 顺序推断不可靠**，这里改用「e-date 是日期、e-title 是标题、
剩下的按位置取倒数第二当地点」。表头行 `.position-item.small` 必须排除。

这也是本项目里少数**列表就带发布日期**的站，publish_at 直接取「发布于」那行。

source.params:
  base: 站点根，如 "https://jobs.siemens.com.cn"
  tenant: 第一段路径，如 "siemens"
  recruit_type_map: {"校园": "CAMPUSRECRUITMENT", ...}，默认见 DEFAULT_TYPE_MAP
  page_size: 每页条数，默认 15（站点分页控件里的 data-pagemax）
  fetch_detail: 是否进详情页取 JD 正文，默认 True。
      **开了会对每个岗位多发一次请求**（西门子 50 条 ≈ 50 次），1 rps 下约 1 分钟。
      列表卡片里**没有**正文，所以不开就是 0% JD 覆盖。
"""

import html
import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, cities_from_text, date_only, grad_year_from_text

DEFAULT_PAGE_SIZE = 15  # 站点 data-pagemax 的默认值；不是 GET 首页的 10（那是首屏内联的条数）
# 站点的 recruitmentType 是枚举，不是自由文本；映射固定在这里，源配置只挑要哪几类
DEFAULT_TYPE_MAP = {
    "campus": "CAMPUSRECRUITMENT",
    "intern": "INTERNSHIPRECRUITMENT",
    "social": "SOCIALRECRUITMENT",
}
# 卡片边界：从 `pid="…"` 一直取到**下一张卡片**（或列表结束 `</div>\s*</div>`）。
# 不能用 `<div class="position-item` 做前瞻 —— 卡片内部有
# `<div class="position-item-container">`，会在那里提前截断（2026-10-26 实测 rest 只剩 52 字符）。
ITEM = re.compile(r'pid="(?P<pid>[^"]+)"(?P<rest>.*?)'
                  r'(?=<div class="position-item |</div>\s*</div>\s*</div>|<div class="pagination|$)', re.S)
# `<h4 class="title" >` 后面可能有一个空格（英特尔实测），所以不能写死 `class="title">`。
# 中间还可能有 `<span class="icons i-title"></span>`，用 .*? 吃掉。
TITLE = re.compile(r'<h4 class="title"\s*>.*?<span class="txt">(?P<t>.*?)</span>', re.S)
TIME = re.compile(r'<div class="time">\s*发布于[:：]\s*(?P<d>[\d\-./]+)', re.S)
# 片段头部写「共41个职位」，比 positionTotal 接口更可信（接口偶尔不带 recruitmentType 会返回全站数）
HEAD_COUNT = re.compile(r'共\s*(?P<n>\d+)\s*个职位')
TOTAL = re.compile(r'"positionTotal"\s*:\s*(\d+)')
# 列表式卡片（无 pid，靠 e-title 里的 detail 链接拿 id）。表头 `.position-item.small` 要排除。
LIST_ITEM = re.compile(r'<div class="position-item">(?P<rest>.*?)</div>\s*(?=\s*<div class="position-item|'
                       r'\s*</div>\s*</div>\s*</div>|\s*<div class="pagination|$)', re.S)
LIST_ID = re.compile(r'positionId=(?P<id>[0-9a-z]+)')
LIST_TITLE = re.compile(r'<div class="ele e-title"[^>]*>(?P<v>.*?)</div>', re.S)
LIST_DATE = re.compile(r'<div class="ele e-date"[^>]*>(?P<v>.*?)</div>', re.S)
LIST_ELE = re.compile(r'<div class="ele [^"]*"[^>]*>(?P<v>.*?)</div>', re.S)
TAG = re.compile(r"<[^>]+>")
# 详情页正文（2026-10-26 实测西门子 position/detail）：<div class="position-description mt-4 mb-4">…</div>
# 注意列表卡片里也有个 `position-details` 类名，别把两者搞混。
DESC = re.compile(r'<div class="position-description[^"]*"[^>]*>(?P<body>.*?)</div>\s*</div>', re.S)
DESC_ALT = re.compile(r'<div class="position-description[^"]*"[^>]*>(?P<body>.*?)(?=<div class="position-|</div>\s*</div>\s*</div>)', re.S)
# 详情页的绝对发布时间（列表页给「发布于: 2026-10-08」，详情页偶尔只有这个）
DETAIL_DATE = re.compile(r'发布时间\s*[:：]\s*(?P<d>[\d\-./]+)')


def _text(fragment: str | None) -> str | None:
    if not fragment:
        return None
    s = html.unescape(TAG.sub(" ", fragment))
    return re.sub(r"\s+", " ", s).strip() or None


def _field(rest: str, label: str) -> str | None:
    """从卡片里的 `<li><span class="txt">工作地点：上海,北京</span></li>` 取出冒号后的值。"""
    m = re.search(rf'<span class="txt">\s*{re.escape(label)}\s*[:：]\s*(?P<v>.*?)</span>', rest, re.S)
    return _text(m.group("v")) if m else None


def _city_field(rest: str) -> str | None:
    """地点有两种写法：

      1. `<li class="ele"><span class="txt">工作地点：上海,北京</span></li>`（西门子）
      2. `<li class="ele e-city"><span class="txt">上海</span></li>`（英特尔）
         —— 没有「工作地点：」前缀，值直接就是地名，所以不能用 _field("工作地点")。
    """
    v = _field(rest, "工作地点")
    if v:
        return v
    # 3. `<li class="ele e-city"><span class="txt">工作城市：上海</span></li>`（辉瑞 2026-10-27 实测，
    #    e-city 类名对上了但值里带着「工作城市：」前缀）。先按前缀取，取不到再当裸地名用——
    #    否则 cities 会变成 ['工作城市：上海']，日历按城市筛直接失效。
    v = _field(rest, "工作城市")
    if v:
        return v
    m = re.search(r'<li class="ele e-city"[^>]*>\s*<span class="txt">(?P<v>.*?)</span>', rest, re.S)
    if not m:
        return None
    v = _text(m.group("v"))
    return re.sub(r"^(?:工作城市|工作地点|城市)\s*[:：]\s*", "", v) if v else None


def _parse_list_item(rest: str) -> dict | None:
    """列表式卡片 -> {"pid", "title", "location", "department", "date"}。

    列顺序：e-title / 业务 / 职位类别 / 工作地点 / e-date。地点是**倒数第二个 .ele**
    （最后一个是 e-date）。少于 3 列的卡片（有的站点只给标题+日期）跳过地点。
    """
    tm = LIST_TITLE.search(rest)
    if not tm:
        return None
    title = _text(tm.group("v"))
    dm = LIST_ID.search(rest)
    if not title or not dm:
        return None
    eles = [_text(m.group("v")) for m in LIST_ELE.finditer(rest)]
    date_m = LIST_DATE.search(rest)
    location = None
    department = None
    # eles[0] 是标题；e-date 也在 eles 里（列名都是 ele），但值不一定是日期
    body = [e for e in eles[1:] if e]
    if date_m:
        body = [e for e in body if e != _text(date_m.group("v"))]
    if len(body) >= 2:
        location = body[-1]
        department = body[-2]
    elif body:
        location = body[0]
    return {"pid": dm.group("id"), "title": title, "location": location,
            "department": department, "date": _text(date_m.group("v")) if date_m else None}


def _job_id(rest: str) -> str | None:
    """`JobID:522053` 是站点自己的岗位号，比 pid 更适合给人看，但 pid 才是详情页主键。"""
    m = re.search(r'<span class="txt">\s*JobID\s*[:：]\s*(?P<v>[\w\-]+)', rest, re.I)
    return m.group("v") if m else None


@register
class Tupu360Adapter(Adapter):
    id = "tupu360"

    def _list_url(self, recruitment: str) -> str:
        p = self.source.params
        return f"{p['base'].rstrip('/')}/{p['tenant']}/position/index?recruitmentType={recruitment}"

    def _page_url(self, recruitment: str) -> str:
        p = self.source.params
        return f"{p['base'].rstrip('/')}/{p['tenant']}/position/nextPageList"

    def _total(self, recruitment: str) -> int:
        p = self.source.params
        url = f"{p['base'].rstrip('/')}/{p['tenant']}/position/positionTotal?recruitmentType={recruitment}"
        try:
            data = self.request_json("GET", url, headers={"Referer": self._list_url(recruitment)})
        except Exception:  # noqa: BLE001 — 取不到总数就只翻到空页为止
            return 0
        return int(data.get("positionTotal") or 0)

    def _fetch_page(self, recruitment: str, page: int, size: int) -> str:
        """第 1 页走 GET index（服务端直出，最省事），后续页走 POST nextPageList。"""
        if page == 1:
            return self.request_text("GET", self._list_url(recruitment))
        return self.request_text(
            "POST",
            self._page_url(recruitment),
            data={"recruitmentType": recruitment, "offset": str((page - 1) * size), "max": str(size)},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": self._list_url(recruitment),
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )

    def _detail_url(self, pid: str, code: str) -> str:
        p = self.source.params
        return (f"{p['base'].rstrip('/')}/{p['tenant']}/position/detail"
                f"?positionId={pid}&recruitmentType={code}")

    def _detail(self, pid: str, code: str) -> str:
        """进详情页取 JD 正文。失败只丢正文，不影响这条岗位入库。"""
        try:
            return self.request_text("GET", self._detail_url(pid, code))
        except Exception:  # noqa: BLE001 — 详情 404/超时不该让整个源失败
            return ""

    def fetch_raw(self) -> Iterator[dict]:
        p = self.source.params
        size = int(p.get("page_size", DEFAULT_PAGE_SIZE))
        fetch_detail = bool(p.get("fetch_detail", True))
        type_map = {**DEFAULT_TYPE_MAP, **(p.get("recruit_type_map") or {})}
        for rtype in self.source.recruit_types:
            code = type_map[rtype]
            total = self._total(code)
            seen: set[str] = set()
            page = 1
            while True:
                body = self._fetch_page(code, page, size)
                if page > 1:
                    # 片段头的「共N个职位」是全量口径，比 positionTotal 更能兜住接口缺参的情况
                    m = HEAD_COUNT.search(body)
                    if m and not total:
                        total = int(m.group("n"))
                fresh = 0
                for m in ITEM.finditer(body):
                    pid = m.group("pid")
                    if pid in seen:
                        continue
                    seen.add(pid)
                    fresh += 1
                    yield {"pid": pid, "rest": m.group("rest"), "recruit_type": rtype, "code": code,
                           "layout": "card",
                           "detail": self._detail(pid, code) if fetch_detail else ""}
                if not fresh:
                    # 没有卡片式（无 pid）就试列表式
                    for m in LIST_ITEM.finditer(body):
                        parsed = _parse_list_item(m.group("rest"))
                        if not parsed or parsed["pid"] in seen:
                            continue
                        seen.add(parsed["pid"])
                        fresh += 1
                        yield {**parsed, "recruit_type": rtype, "code": code, "layout": "list",
                               "detail": self._detail(parsed["pid"], code) if fetch_detail else ""}
                # 这里必须 break 而不是 return：return 会把**后面所有招聘类型**一起终止。
                # 2026-10-26 实测踩到——西门子 campus 41 条抓完后直接 return，intern 的 9 条
                # 一条都没进入结果，而 CLI 仍然显示 `1 ok / opened: 41`，完全看不出漏抓。
                if not fresh:  # 翻页失效（一直返回同一页）时整页都是已见过的 pid
                    break
                if total and len(seen) >= total:
                    break
                if not total and fresh < size:
                    break
                if self.source.max_pages and page >= self.source.max_pages:
                    break
                page += 1

    def normalize(self, raw: dict) -> Job:
        if raw.get("layout") == "list":
            return self._normalize_list(raw)
        rest = raw["rest"]
        t = TITLE.search(rest)
        title = _text(t.group("t")) if t else None
        if not title:
            raise SkipRecord
        rtype = raw["recruit_type"]
        place = _city_field(rest) or ""
        pid = raw["pid"]
        time_m = TIME.search(rest)
        detail = raw.get("detail") or ""
        return Job(
            source_id=self.source.id,
            source_job_id=str(pid),
            company=self.source.company,
            url=self._detail_url(pid, raw["code"]),
            title=title,
            recruit_type=rtype,
            grad_year=grad_year_from_text(title, loose=True) if rtype != "social" else None,
            batch=batch_from_text(title) if rtype == "campus" else None,
            cities=cities_from_text(place),
            department=_field(rest, "职能类别"),
            publish_at=date_only(time_m.group("d")) if time_m else _detail_date(detail),
            description=_detail_desc(detail),
        )

    def _normalize_list(self, raw: dict) -> Job:
        """列表式卡片：字段已经在 _parse_list_item 里拆好，这里只做类型归一。"""
        rtype = raw["recruit_type"]
        title = raw["title"]
        detail = raw.get("detail") or ""
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw["pid"]),
            company=self.source.company,
            url=self._detail_url(raw["pid"], raw["code"]),
            title=title,
            recruit_type=rtype,
            grad_year=grad_year_from_text(title, loose=True) if rtype != "social" else None,
            batch=batch_from_text(title) if rtype == "campus" else None,
            cities=cities_from_text(raw.get("location")),
            department=raw.get("department"),
            publish_at=date_only(raw["date"]) if raw.get("date") else _detail_date(detail),
            description=_detail_desc(detail),
        )


def _detail_desc(detail: str) -> str | None:
    """详情页正文。先试 `</div></div>` 收尾的精确式，不行再用前瞻式兜底。"""
    if not detail:
        return None
    m = DESC.search(detail) or DESC_ALT.search(detail)
    if not m:
        return None
    body = m.group("body")
    # 正文里的 <div>/<br> 是分段标记，直接 TAG 掉会把段落连成一片，先换成换行。
    # 注意 `_text()` 会把所有空白压成一个空格 —— 那样换行就白换了（2026-10-26 实测），
    # 所以这里自己走一遍：先去标签、再解实体、只压缩空格和制表符，保留换行。
    body = re.sub(r"<br\s*/?>|</div>|</p>|</li>", "\n", body, flags=re.I)
    txt = html.unescape(TAG.sub(" ", body))
    txt = re.sub(r"[ \t\r\f\v]+", " ", txt)
    txt = re.sub(r"\n\s*\n\s*\n+", "\n\n", txt)
    return txt.strip() or None


def _detail_date(detail: str) -> str | None:
    m = DETAIL_DATE.search(detail or "")
    return date_only(m.group("d")) if m else None
