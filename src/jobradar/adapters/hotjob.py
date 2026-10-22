"""hotjob（大易云）招聘门户：`{host}/wecruit/...`，平台型适配器。

侦察：docs/recon/hotjob.md。列表与详情都是公开 GET JSON（`iSaJAx=isAjax`），无需登录/签名。

source.params:
  tenant: 站点 id，如 "SU60a6449a2f9d2430fdc11a19"（页面 URL 第一段，必填）
  host: 默认 "wecruit.hotjob.cn"；自定义域名如 "yili.hotjob.cn"
  page_size: 请求的每页条数（服务端可能更小），默认 50
  fetch_detail: 是否逐岗请求详情拿 JD 正文，默认 True（契约要求 ≥90% 有正文）

已知：`recruitType` 1=校园、2=社招、3=实习；城市在 `workPlaceStr`（如「长沙市-长沙县」）。
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, grad_year_from_text

RECRUIT_CODE = {"campus": "1", "social": "2", "intern": "3"}
PORTAL = {"campus": "campus", "social": "social", "intern": "campus"}
DEFAULT_HOST = "wecruit.hotjob.cn"
DEFAULT_PAGE_SIZE = 50


@register
class HotjobAdapter(Adapter):
    id = "hotjob"

    @property
    def tenant(self) -> str:
        return self.source.params["tenant"]

    @property
    def host(self) -> str:
        return self.source.params.get("host", DEFAULT_HOST)

    def _params(self, **extra) -> dict:
        # 不加 	=<毫秒时间戳>：服务端不校验，但带随机参数会让 fixtures 无法回放
        return {"iSaJAx": "isAjax", "request_locale": "zh_CN", **extra}

    def _list(self, code: str, page: int) -> dict:
        return self.request_json(
            "GET", f"https://{self.host}/wecruit/positionInfo/listPosition/{self.tenant}",
            params=self._params(isFrompb="true", recruitType=code,
                                pageSize=str(int(self.source.params.get("page_size", DEFAULT_PAGE_SIZE))),
                                currentPage=str(page)),
            headers={"Referer": f"https://{self.host}/{self.tenant}/pb/social.html"},
        )

    def _detail(self, post_id: str) -> dict:
        data = self.request_json(
            "GET", f"https://{self.host}/wecruit/positionInfo/listPositionDetail/{self.tenant}",
            params=self._params(postId=post_id),
            headers={"Referer": f"https://{self.host}/{self.tenant}/pb/posDetail.html?postId={post_id}"},
        )
        return data.get("data") or {}

    def fetch_raw(self) -> Iterator[dict]:
        fetch_detail = bool(self.source.params.get("fetch_detail", True))
        for rtype in self.source.recruit_types:
            code = RECRUIT_CODE[rtype]
            page = 1
            while True:
                data = self._list(code, page)
                form = (data.get("data") or {}).get("pageForm") or {}
                items = form.get("pageData") or []
                if not items:
                    break
                for it in items:
                    detail = {}
                    if fetch_detail and it.get("postId"):
                        try:
                            detail = self._detail(it["postId"])
                        except Exception:  # noqa: BLE001 — 详情失败不影响列表入库，只是缺正文
                            detail = {}
                    yield {"list": it, "detail": detail, "recruit_type": rtype}
                total = int(form.get("totalPage") or 0)
                if page >= total:
                    break
                if self.source.max_pages and page >= self.source.max_pages:
                    break
                page += 1

    def normalize(self, raw: dict) -> Job:
        it, detail = raw["list"], raw.get("detail") or {}
        post_id = it.get("postId")
        title = (it.get("postName") or "").strip()
        if not post_id or not title:
            raise SkipRecord
        rtype = raw["recruit_type"]
        places = [p for p in (it.get("workPlaceStr") or "").split("-") if p.strip()]
        cities = [p.strip().removesuffix("市") for p in places[:1]]  # 只要城市级，不要区县
        return Job(
            source_id=self.source.id,
            source_job_id=str(post_id),
            company=self.source.company,
            url=(f"https://{self.host}/{self.tenant}/pb/posDetail.html"
                 f"?postId={post_id}&postType={PORTAL[rtype]}"),
            title=title,
            recruit_type=rtype,
            grad_year=grad_year_from_text(title, loose=True) if rtype != "social" else None,
            batch=batch_from_text(title) if rtype == "campus" else None,
            cities=cities,
            degree_min=(detail.get("education") or it.get("educationStr") or None),
            department=(it.get("company") or None),
            description=(detail.get("workContent") or None),
            requirements=(detail.get("serviceCondition") or None),
        )
