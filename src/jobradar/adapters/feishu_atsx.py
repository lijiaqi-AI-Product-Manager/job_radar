"""飞书招聘 ATSX 门户通用适配器（campus 站）。

字节跳动 `jobs.bytedance.com`、蔚来 `nio.jobs.feishu.cn`、小鹏 `xiaopeng.jobs.feishu.cn`、
Momenta、月之暗面……用的是**同一套 ATSX 前端 + 同一套匿名 JSON 接口**，只是域名与
`website-path` 不同。2026-10-26 逐个实测（见 docs/recon/feishu-atsx.md §1）：

  | 门户 | csrf | 列表 | 说明 |
  |---|---|---|---|
  | jobs.bytedance.com | 200 | 200 | 7044 条 |
  | nio.jobs.feishu.cn/campus | 200 | 200 | 869 条，project="2027届校园招聘-正式批" |
  | xiaopeng.jobs.feishu.cn/index | 200 | 200 | 1588 条，混排社招，需按 recruit_type 父级过滤 |
  | momenta.jobs.feishu.cn/campus | 200 | 200 | 30 条，project="Mstar计划" |
  | moonshot.jobs.feishu.cn/campus | 200 | 200 | 0 条（门户当时无开放岗位） |

匿名会话（CLAUDE.md 铁律 1）：
  1) `POST /api/v1/csrf/token` body `{"portal_entrance":1}` → 在 `data.token` 返回会话令牌；
  2) 列表 `POST /api/v1/search/job/posts`，请求头带 `x-csrf-token: <data.token>`（**必须是 body 里
     那个原值**，不是 URL 编码后的 cookie 值）+ `Accept: application/json` → 200。
  两个坑都实测过：缺 token 或缺 Accept → **405**（不是 401/403，极易误判成"接口不存在"）；
  页面里的 `_signature` 参数**不校验**（篡改后仍 200），所以不涉及逆向签名。

列表一次返回完整字段：职责 `description`、要求 `requirement`、职类 `job_category`、
城市 `city_list`（可能多个）、招聘项目 `job_subject`、类型 `recruit_type`（正式/实习/全职）、
发布时间 `publish_time`（毫秒）。**无需逐岗请求详情页。**

source.params:
  base_url: 门户根地址，如 `https://nio.jobs.feishu.cn`
  website_path: 站点路径前缀，默认 `campus`。门户首页挂在 `/index` 的写 `index`——
               它决定 `portal-channel` / `website-path` / `Referer`，也决定岗位详情 URL 的形状。
  portal_type: 门户类型，默认 3（校园站；实测与 6 返回同一份数据）
  keyword: 关键词过滤，默认空（全量）。留给"门户首页挂在 /index、且校招岗只占极少数"的场景，
          见 docs/recon/feishu-atsx.md §2 关于小鹏的记录。
  page_size: 每页条数，默认 100
  max_pages: 上限（契约测试用）
  job_url: 岗位详情 URL 模板，默认 `{base}/{website_path}/position/{id}/detail`

关于"校招 / 实习 / 社招"的判定见 `recruit_type_of()`——不同门户给的字段不一样：
字节跳动给 `job_subject="2027届校园招聘"`，蔚来给 `"2027届校园招聘-正式批"`，
小鹏的社招/校招混在同一个门户里且 `job_subject` 为空，只能靠 `recruit_type` 的父子级判断。
"""

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, categorize, grad_year_from_jd, grad_year_from_text

DEFAULT_BASE = "https://jobs.bytedance.com"
DEFAULT_PATH = "campus"
PAGE_SIZE = 100
PORTAL_TYPE = 3
CST = timezone(timedelta(hours=8))

# 招聘项目名/类型名 -> recruit_type。
_INTERN_WORDS = ("实习", "intern")
_SOCIAL_WORDS = ("社招", "社会招聘", "社会", "experienced")
# recruit_type 树的父节点名（"校招"/"社招"）——小鹏这类门户只给这一层，不给项目名
_PARENT_CAMPUS = ("校招", "校园招聘")
_PARENT_SOCIAL = ("社招", "社会招聘")


def _name_of(obj) -> str:
    """ATSX 的 name 有时是字符串，有时是 {zh_cn: ...} 的 i18n 对象。"""
    if isinstance(obj, dict):
        return obj.get("zh_cn") or obj.get("name") or ""
    return obj or ""


def recruit_type_of(item: dict) -> str | None:
    """校招/实习返回对应类型，社招或不认识的返回 None（调用方跳过）。

    判定顺序（从严到宽，任一环给出结论就停）：
      1. 项目名或类型名里出现"社招/社会招聘" → 社招，跳过；
      2. 出现"实习/intern" → 实习；
      3. 出现"校/届" → 校招；
      4. **向上找 recruit_type 的父节点**：父级是"校招"→ 校招；父级是"社招"→ 跳过。
         第 4 步是为小鹏这种门户加的：它 `job_subject` 为空、`recruit_type.name="全职"`，
         唯一能区分校招/社招的是 `recruit_type.parent.name`。
    """
    subject = _name_of((item.get("job_subject") or {}).get("name"))
    rtype = item.get("recruit_type") or {}
    rtype_name = rtype.get("name") or ""
    # 类型名本身也要过 i18n（个别门户给的是 `{"zh_cn": "全职"}` 而不是字符串）。
    if not isinstance(rtype_name, str):
        rtype_name = _name_of(rtype_name.get("zh_cn")) if isinstance(rtype_name, dict) else str(rtype_name)
    text = f"{subject} {rtype_name}"
    if any(w in text for w in _SOCIAL_WORDS):
        return None
    if any(w.lower() in text.lower() for w in _INTERN_WORDS):
        return "intern"
    if "校" in text or "届" in text:
        return "campus"
    parent = rtype.get("parent") or {}
    ptext = f"{parent.get('name') or ''} {_name_of(parent.get('i18n_name'))}"
    if any(w in ptext for w in _PARENT_SOCIAL):
        return "social"
    if any(w in ptext for w in _PARENT_CAMPUS):
        return "campus"
    # 5. 门户**只发社招**时没有父级：`recruit_type.name` 直接就是「全职」。
    #    「全职」在飞书 ATSX 的语义是「非实习」，也就是社招。
    if rtype_name.strip() in ("全职", "Full-time", "Full time", "full_time"):
        return "social"
    return None


def cities_of(item: dict) -> list[str]:
    """city_list 才是全量（city_info 只是第一个）。按站点顺序去重。"""
    out: list[str] = []
    for c in item.get("city_list") or []:
        name = (c or {}).get("name")
        if name and name not in out:
            out.append(name)
    if not out and (item.get("city_info") or {}).get("name"):
        out.append(item["city_info"]["name"])
    return out


def publish_date(ms) -> str | None:
    """publish_time 是毫秒时间戳，按东八区落到日期。0/None/明显越界的返回 None，不猜。

    先做范围判断再转 datetime：`datetime.fromtimestamp` 对超界值抛 `ValueError`/`OverflowError`，
    而站点偶尔会返回 0 或哨兵值，一条脏数据不该把整轮抓取打断。
    """
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0 or ms > 2_208_988_800_000:  # 2040-01-01 之后一律不认
        return None
    try:
        d = datetime.fromtimestamp(ms / 1000, CST).date()
    except (ValueError, OverflowError, OSError):
        return None
    return d.isoformat() if date(2000, 1, 1) <= d <= date(2040, 12, 31) else None


@register
class FeishuAtsxAdapter(Adapter):
    """任意飞书招聘 ATSX 门户。source.params.base_url 决定是哪一家。"""

    id = "feishu_atsx"
    # csrf token 是站点下发给匿名访客的会话值，记 fixtures 时脱敏
    secret_patterns = [r'"token"\s*:\s*"([^"]+)"']

    # ---- 门户参数 ----
    @property
    def base_url(self) -> str:
        return (self.source.params.get("base_url") or DEFAULT_BASE).rstrip("/")

    @property
    def website_path(self) -> str:
        return (self.source.params.get("website_path") or DEFAULT_PATH).strip("/") or DEFAULT_PATH

    def _portal(self) -> int:
        return int(self.source.params.get("portal_type", PORTAL_TYPE))

    def job_url(self, jid: str) -> str:
        tpl = self.source.params.get("job_url")
        if tpl:
            return str(tpl).format(base=self.base_url, website_path=self.website_path, id=jid)
        return f"{self.base_url}/{self.website_path}/position/{jid}/detail"

    # ---- 会话 ----
    def _csrf(self) -> tuple[str, dict]:
        base = self.base_url
        data = self.request_json("POST", f"{base}/api/v1/csrf/token", json={"portal_entrance": 1})
        token = (data.get("data") or {}).get("token") or ""
        if not token:
            raise RuntimeError(f"{self.id}: {base} 没有返回 csrf token")
        path = self.website_path
        hdrs = {
            "x-csrf-token": token,
            "accept": "application/json, text/plain, */*",
            "portal-channel": path,
            "portal-platform": "pc",
            "origin": base,
            "referer": f"{base}/{path}",
        }
        # **`website-path: index` 会让服务端回 `{"code": -9000003, "message": "site not exist"}`**。
        # 2026-10-27 实测：商汤 87 岗、分贝通 14 岗的门户挂在 `/index`，带上这个头就全被判定为
        # 「站点不存在」；去掉头立刻 200 + count=87。而 `/campus` 这类真站点带了才有数据
        # （不带会掉回 405）。所以只在门户不是 `/index` 时才发。
        if path != "index":
            hdrs["website-path"] = path
        return token, hdrs

    def fetch_raw(self) -> Iterator[dict]:
        try:
            yield from self._fetch()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"{self.id} {urlsplit(str(e.request.url)).netloc} {e.request.url.path} "
                f"HTTP {e.response.status_code}"
            ) from None

    def _fetch(self) -> Iterator[dict]:
        token, headers = self._csrf()
        size = int(self.source.params.get("page_size", PAGE_SIZE))
        portal = self._portal()
        keyword = str(self.source.params.get("keyword") or "")
        list_url = f"{self.base_url}/api/v1/search/job/posts"
        offset = 0
        total = None
        while True:
            params = {"portal_type": portal, "limit": size, "offset": offset, "portal_entrance": 1}
            if keyword:
                params["keyword"] = keyword
            body = {
                "keyword": keyword, "limit": size, "offset": offset,
                "job_category_id_list": [], "tag_id_list": [], "location_code_list": [],
                "subject_id_list": [], "recruitment_id_list": [], "portal_type": portal,
                "job_function_id_list": [], "storefront_id_list": [], "portal_entrance": 1,
            }
            data = self.request_json("POST", list_url, params=params, json=body, headers=headers)
            payload = data.get("data") or {}
            items = payload.get("job_post_list") or []
            if total is None:
                total = payload.get("count")
            yield from items
            offset += size
            if not items or (total is not None and offset >= int(total)):
                return
            if self.source.max_pages and offset >= self.source.max_pages * size:
                return
            # token 有寿命，翻页过程中过期就换一个（实测约 10 分钟仍有效，这里只做兜底）
            if offset % (size * 20) == 0:
                token, headers = self._csrf()

    # ---- 归一 ----
    def normalize(self, raw: dict) -> Job:
        title = (raw.get("title") or "").strip()
        jid = raw.get("id")
        # 跳过时带原因：2026-10-27 商汤 87 条只入库 1 条，就是因为裸 raise SkipRecord
        # 让日志里只剩一行「SKIP xxx | 」，完全看不出命中的是哪一支。
        if not jid or not title:
            raise SkipRecord(f"缺 id 或 title（id={jid!r} title={title!r}）")
        rtype = recruit_type_of(raw)
        if rtype is None:
            raise SkipRecord(f"招聘类型无法判定（recruit_type={raw.get('recruit_type')}）")
        # 与 beisen/hotjob 保持一致：只收 source.recruit_types 里声明的类型。
        # 2026-10-28 之前这里没过滤，只配了 [campus, intern] 的飞书源照样把社招岗写进库
        # （度小满 49 条里 41 条是社招），同一份数据集里两类源的口径不一致。
        if rtype not in self.source.recruit_types:
            raise SkipRecord(f"招聘类型 {rtype} 不在 source.recruit_types 里")
        subject = _name_of((raw.get("job_subject") or {}).get("name"))
        # 届别只认项目名里写明的（"2027届校园招聘"）。
        grad = grad_year_from_text(subject)
        if grad is None:
            # 项目名没写才看标题；标题只有「Seed大模型人才校招」这类项目名时同样取不到。
            grad = grad_year_from_text(f"{subject} {title}", loose=True)
        if grad is None:
            grad = grad_year_from_jd(raw.get("description"), raw.get("requirement"))
            # 用 JD 正文兜底只对"最近发布"的岗位可信。实测（2026-10-26）：2023 年就挂着的
            # 「客户端开发实习生-抖音研发」JD 里写的是"2023届"，但岗位一直沿用至今、JD 早已过期，
            # 拿它当届次会写出「2023届在招」这种明显错误。发布时间早于本年度招季起点（7-1）不兜底。
            pub = publish_date(raw.get("publish_time"))
            if pub is None or pub < f"{date.today().year}-07-01":
                grad = None
        # job_category 树：站点只给叶子（算法 / 后端 / 运营…），父节点是"研发"这类大方向。
        # 用 taxonomy 的归类口径而不是自造树，跨公司才能对齐（CLAUDE.md：不要自造分类）。
        cat, subcat = categorize(title)
        if cat is None:
            # taxonomy 没命中时退回站点自己的职类名，至少保留信息量
            cat = (raw.get("job_category") or {}).get("name")
        return Job(
            source_id=self.source.id,
            source_job_id=str(jid),
            company=self.source.company,
            url=self.job_url(str(jid)),
            title=title,
            recruit_type=rtype,
            category=cat,
            subcategory=subcat,
            grad_year=grad,
            batch=batch_from_text(subject),
            cities=cities_of(raw),
            publish_at=publish_date(raw.get("publish_time")),
            description=(raw.get("description") or "").strip() or None,
            requirements=(raw.get("requirement") or "").strip() or None,
        )
