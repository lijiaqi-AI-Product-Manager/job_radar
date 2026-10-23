"""hotjob（大易云）**老版 wt 门户**：`{host}/wt/{tenant}/...`，平台型适配器。

和新版 `hotjob`（`/wecruit/...`）不是同一套接口：老版页面是服务端渲染的 Vue 模板，
数据来自同域的公开 JSON：

    GET https://{host}/wt/{tenant}/web/json/position/list
        ?positionType=&comPart=&sicCorpCode=&brandCode=1&releaseTime=&trademark=1
        &recruitType={1校招|2社招|3实习}&projectId=&lanType=1&workPlace=&page={n}&keyWord=

返回 `{"pageCount": N, "postList": [...]}`，列表里**自带 JD 正文**
（`workContent` 职责 + `serviceCondition` 要求），所以不需要再逐岗请求详情。

侦察：docs/recon/hotjob-legacy.md（伊利、易方达两个租户实测）。

source.params:
  tenant: 站点路径段，如 "yili"（必填）
  host: 默认 "www.hotjob.cn"；自定义域名如 "yili.hotjob.cn"
  brand_code: 默认 "1"
"""

import json
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, grad_year_from_text

RECRUIT_CODE = {"campus": "1", "social": "2", "intern": "3"}
DEFAULT_HOST = "www.hotjob.cn"


@register
class HotjobLegacyAdapter(Adapter):
    id = "hotjob_legacy"

    @property
    def tenant(self) -> str:
        return self.source.params["tenant"]

    @property
    def host(self) -> str:
        return self.source.params.get("host", DEFAULT_HOST)

    def _list(self, code: str, page: int) -> dict:
        url = f"https://{self.host}/wt/{self.tenant}/web/json/position/list"
        params = {
            "positionType": "", "comPart": "", "sicCorpCode": "",
            "brandCode": str(self.source.params.get("brand_code", "1")),
            "releaseTime": "", "trademark": "1", "recruitType": code,
            "projectId": "", "lanType": "1", "workPlace": "", "page": str(page), "keyWord": "",
        }
        # 站点返回 text/html 但正文是 JSON，所以不能用 request_json（它按 content-type 判断）
        text = self.request_text("GET", url, params=params,
                                 headers={"X-Requested-With": "XMLHttpRequest",
                                          "Referer": f"https://{self.host}/wt/{self.tenant}/web/index"})
        return json.loads(text)

    def fetch_raw(self) -> Iterator[dict]:
        for rtype in self.source.recruit_types:
            code = RECRUIT_CODE[rtype]
            page = 1
            while True:
                data = self._list(code, page)
                items = data.get("postList") or []
                if not items:
                    break
                for it in items:
                    yield {"item": it, "recruit_type": rtype}
                total = int(data.get("pageCount") or 0)
                if page >= total:
                    break
                if self.source.max_pages and page >= self.source.max_pages:
                    break
                page += 1

    def normalize(self, raw: dict) -> Job:
        it = raw["item"]
        post_id = it.get("postId")
        title = (it.get("postName") or "").strip()
        if not post_id or not title:
            raise SkipRecord
        rtype = raw["recruit_type"]
        # workPlace 形如「北京市-丰台区」，只要城市级
        place = (it.get("workPlace") or "").split("-")[0].strip()
        cities = [place.removesuffix("市")] if place else []
        return Job(
            source_id=self.source.id,
            source_job_id=str(post_id),
            company=self.source.company,
            url=(f"https://{self.host}/wt/{self.tenant}/web/index/webPositionN300!getOnePosition"
                 f"?postId={post_id}&brandCode=1&recruitType={RECRUIT_CODE[rtype]}&lanType=1&columnId=1&importPost=0"),
            title=title,
            recruit_type=rtype,
            grad_year=grad_year_from_text(title, loose=True) if rtype != "social" else None,
            batch=batch_from_text(title) if rtype == "campus" else None,
            cities=cities,
            degree_min=(it.get("education") or None),
            department=(it.get("orgName") or None),
            description=(it.get("workContent") or None),
            requirements=(it.get("serviceCondition") or None),
        )
