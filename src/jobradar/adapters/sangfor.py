"""深信服招聘站（`hr.sangfor.com`）—— Nuxt SPA + 匿名 Bearer token 的 WebAPI。

侦察记录（2026-10-27 全部实测）：

  | 环节 | 结论 |
  |---|---|
  | 前端配置 | `GET /config.js` 明文写着 `wshubUrl = 'https://hr.sangfor.com/webapi/'` —— 不是逆向，就是前端给浏览器看的配置 |
  | 拿 token | `GET /webapi/api/connect/token` → `{"access_token": "..."}`，**匿名、无需登录**。注意 `/api/connect/token`（去掉 webapi）是 404 |
  | 列表 | `POST /webapi/api/Jobs`，body 里 `channelId: 0` = 全部渠道（**不是 100/101**，那两个都只返回 31 条校招） |
  | 必须的头 | `X-Requested-With: XMLHttpRequest`（缺了 404）+ `Authorization: Bearer <token>`（缺了 401）+ `Content-Type: application/json`（写 `text/plain` 会 415，虽然前端 axios 默认就是 text/plain） |
  | 分页 | `pageSize` 可以开到 200（实测 142 条一次拿完）；`count` 是总数 |

字段很齐：`title / description(HTML，职责与要求在同一段里) / workPlaceText(逗号分隔的外地城市)
/ functionName(职类) / departmentName(部门) / channelName(渠道，用来判校招/社招/实习) / openedAt`。

source.params:
  channel_id: 渠道 id，默认 0（全部）
  page_size: 默认 200
"""

import html
import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, categorize, grad_year_from_text

BASE = "https://hr.sangfor.com"
API = f"{BASE}/webapi/api"
TOKEN_URL = f"{API}/connect/token"
JOBS_URL = f"{API}/Jobs"
REFERER = f"{BASE}/Sociology"        # 社招页；服务端只校验 Referer 的主机

_TAG = re.compile(r"<[^>]+>")
_SPLIT = re.compile(r"岗位要求|任职要求|任职资格|职位要求|我们希望你")


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    s = html.unescape(_TAG.sub("\n", fragment))
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def _cities(text: str | None) -> list[str]:
    return [c.strip() for c in re.split(r"[,，/、]", text or "") if c.strip()]


def _rtype(channel: str, title: str) -> str:
    """渠道名优先（「27/28届实习生招聘」→ 实习，「社会招聘」→ 社招），标题只做兜底。"""
    ch = channel or ""
    if "实习" in ch or "实习生" in title:
        return "intern"
    if "社会招聘" in ch:
        return "social"
    if "校园招聘" in ch or "校招" in ch or "届" in title:
        return "campus"
    return "social"


@register
class SangforAdapter(Adapter):
    id = "sangfor"

    def _token(self) -> str:
        data = self.request_json("GET", TOKEN_URL, headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": REFERER,
        })
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"sangfor: /api/connect/token 没给 access_token（keys={list(data)[:6]}）")
        return token

    def fetch_raw(self) -> Iterator[dict]:
        token = self._token()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": REFERER,
        }
        size = int(self.source.params.get("page_size", 200))
        channel = int(self.source.params.get("channel_id", 0))
        page = 1
        total = None
        while True:
            body = {"channelId": channel, "page": page, "pageSize": size,
                    "departmentId": 0, "functionId": 0, "kw": "",
                    "locationId": 0, "workPlaceId": 0}
            data = self.request_json("POST", JOBS_URL, json=body, headers=headers)
            if data.get("code") not in (0, None):
                raise RuntimeError(f"sangfor /api/Jobs code={data.get('code')} msg={data.get('message')}")
            payload = data.get("data") or {}
            items = payload.get("listData") or []
            if total is None:
                total = int(payload.get("count") or 0)
            yield from items
            page += 1
            if not items or page * size > total:
                return
            if self.source.max_pages and page > self.source.max_pages:
                return

    def normalize(self, raw: dict) -> Job:
        jid = str(raw.get("positionId") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not jid or not title:
            raise SkipRecord("缺少 positionId 或标题")
        body = _text(raw.get("description"))
        # 深信服把职责与要求写在同一个 HTML 块里，用「岗位要求：」这类小标题分开
        m = _SPLIT.search(body)
        desc, req = (body[: m.start()].strip(), body[m.start():].strip()) if m else (body, "")
        if not desc and not req:
            raise SkipRecord("JD 正文为空")
        channel = str(raw.get("channelName") or "")
        rtype = _rtype(channel, title)
        opened = str(raw.get("openedAt") or "").strip()[:10] or None
        cat, sub = categorize(title)
        return Job(
            source_id=self.source.id,
            source_job_id=jid,
            company=self.source.company,
            url=f"{BASE}/Sociology?jobId={jid}",
            title=title,
            recruit_type=rtype,
            category=cat or (raw.get("functionName") or None),
            subcategory=sub,
            grad_year=grad_year_from_text(f"{channel} {title}"),
            batch=batch_from_text(channel),
            cities=_cities(raw.get("workPlaceText")),
            department=str(raw.get("departmentName") or "").strip() or None,
            publish_at=opened,
            description=desc or None,
            requirements=req or None,
        )
