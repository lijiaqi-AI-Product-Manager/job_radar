"""北森招聘门户（新版，{tenant}.zhiye.com）。平台型：一个适配器服务所有新版门户租户。
侦察：docs/recon/beisen.md。旧版服务端渲染门户（如 smics）不走此适配器。

source.params:
  tenant: 子域名，如 "fosunpharma"
  page_size: 每页条数，默认 100（录 fixtures 时用小值）

已知缺口：列表接口的 LocNames 恒为空，城市暂缺（不从标题猜）。
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, grad_year_from_text

LIST_URL = "https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList"
DETAIL_URL = "https://{tenant}.zhiye.com/{portal}/detail?jobAdId={id}"
PAGE_SIZE = 100
# CategoryId 是北森门户的招聘类型
RECRUIT_TYPE = {"1": "social", "2": "campus", "3": "intern", "5": "social"}  # 5：第二个社招页面（专家/资深岗）
PORTAL = {"social": "social", "campus": "campus", "intern": "intern"}


@register
class BeisenAdapter(Adapter):
    id = "beisen"

    @property
    def tenant(self) -> str:
        return self.source.params["tenant"]

    def fetch_raw(self) -> Iterator[dict]:
        size = int(self.source.params.get("page_size", PAGE_SIZE))
        page = 0
        while True:
            data = self.request_json("POST", LIST_URL.format(tenant=self.tenant), json={
                "PageIndex": page, "PageSize": size, "KeyWords": "", "SpecialType": 0, "PortalId": "",
            })
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

    def normalize(self, raw: dict) -> Job:
        recruit_type = RECRUIT_TYPE.get(str(raw.get("CategoryId")))
        if not raw.get("Id") or not raw.get("JobAdName") or recruit_type is None:
            raise SkipRecord
        if recruit_type not in self.source.recruit_types:
            raise SkipRecord
        title = raw["JobAdName"].strip()
        cities = [c.strip() for c in (raw.get("LocNames") or []) if isinstance(c, str) and c.strip()]
        return Job(
            source_id=self.source.id,
            source_job_id=raw["Id"],
            company=self.source.company,
            url=DETAIL_URL.format(tenant=self.tenant, portal=PORTAL[recruit_type], id=raw["Id"]),
            title=title,
            recruit_type=recruit_type,
            grad_year=grad_year_from_text(title) if recruit_type != "social" else None,
            batch=batch_from_text(title) if recruit_type == "campus" else None,
            cities=cities,
            degree_min=raw.get("Degree") or None,
            description=raw.get("Duty") or None,
            requirements=raw.get("Require") or None,
        )
