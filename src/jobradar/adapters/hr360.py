"""360 招聘（`hr.360.cn`）——奇虎三六零的社招/校招门户，自建站。

侦察记录（2026-10-27 全部实测）：

  | 环节 | 结论 |
  |---|---|
  | 列表 `POST /v2/index/getlistsearch` | 需要 `X-Requested-With: XMLHttpRequest` + `Referer: https://hr.360.cn/hr/list` + `Content-Type: application/json`，缺任一个回 **500**。`limit:10000` 一次给全部（当时 25 岗，不分页，page=2 返回空） |
  | 详情 `GET /v2/index/getjobone?id=<id>` | **必须是 GET**（POST 会 301 到 `/hr/`），并且必须带 `X-Requested-With` 与**岗位详情页的 Referer**，否则 **500 + 空 body** |
  | 详情页 URL | `https://hr.360.cn/hr/detail/<id>`，服务端只是 SPA 壳，真数据全靠上面那个接口 |

参数筛选（keyword / type）被服务端忽略，所以只能全量拉。岗位字段是齐的：
`title / type(职位类别) / area(城市) / date(发布日)`，详情再给 `description`（职责 + 要求同段）。

source.params:
  list_limit: 一次拉多少条，默认 10000（该门户岗位总数远小于此）
  with_detail: 是否逐岗取详情，默认 true。取详情 = 岗位数 次请求，1 rps 下 25 岗约 25 秒。
"""

from collections.abc import Iterator
from datetime import date

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import categorize, grad_year_from_text

BASE = "https://hr.360.cn"
LIST_URL = f"{BASE}/v2/index/getlistsearch"
DETAIL_URL = f"{BASE}/v2/index/getjobone"
LIST_PAGE = f"{BASE}/hr/list"
DETAIL_PAGE = BASE + "/hr/detail/{id}"

# 招聘类型只能从岗位名推：360 的社招列表里会混少量「2027届」字样
INTERN_WORDS = ("实习", "intern")
CAMPUS_WORDS = ("校招", "校园", "应届", "管培", "届")


@register
class Hr360Adapter(Adapter):
    id = "hr360"

    def _headers(self, referer: str) -> dict[str, str]:
        # 三个头缺一不可，缺了就是 500 空 body —— 这条坑实测了两轮。
        return {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "Content-Type": "application/json",
        }

    def fetch_raw(self) -> Iterator[dict]:
        limit = int(self.source.params.get("list_limit", 10000))
        data = self.request_json(
            "POST", LIST_URL,
            json={"page": 1, "limit": limit, "keyword": ""},
            headers=self._headers(LIST_PAGE),
        )
        items = data.get("data") or []
        with_detail = bool(self.source.params.get("with_detail", True))
        for it in items:
            jid = str(it.get("id") or "")
            if not jid:
                continue
            rec = dict(it)
            if with_detail:
                try:
                    d = self.request_json(
                        "GET", DETAIL_URL, params={"id": jid},
                        headers=self._headers(DETAIL_PAGE.format(id=jid)),
                    )
                    detail = d.get("data") or {}
                    rec["description"] = detail.get("description") or ""
                except Exception:  # noqa: BLE001
                    # 详情失败不该让整轮挂掉：列表级字段（标题/城市/日期）仍然可用。
                    rec["description"] = ""
            yield rec

    def normalize(self, raw: dict) -> Job:
        jid = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not jid or not title:
            raise SkipRecord("缺少 id 或标题")
        text = title
        if any(w in text.lower() for w in INTERN_WORDS):
            rtype = "intern"
        elif any(w in text for w in CAMPUS_WORDS):
            rtype = "campus"
        else:
            rtype = "social"
        city = str(raw.get("area") or "").strip()
        desc = str(raw.get("description") or "").strip()
        # 发布时间是 `2026-09-18` 这种纯日期；详情页里的 date 与列表可能差一天，
        # 以列表为准（列表是「最新一版」）。
        pub = _date_or_none(raw.get("date"))
        cat, sub = categorize(title)
        return Job(
            source_id=self.source.id,
            source_job_id=jid,
            company=self.source.company,
            url=DETAIL_PAGE.format(id=jid),
            title=title,
            recruit_type=rtype,
            category=cat,
            subcategory=sub,
            grad_year=grad_year_from_text(text),
            cities=[city] if city else [],
            department=str(raw.get("position") or "") or None,
            publish_at=pub,
            description=desc or None,
        )


def _date_or_none(v) -> str | None:
    s = str(v or "").strip()[:10]
    if len(s) == 10 and s[4] == "-" and s[:4].isdigit():
        try:
            date.fromisoformat(s)
        except ValueError:
            return None
        return s
    return None
