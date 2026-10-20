"""腾讯招聘（社招）careers.tencent.com。侦察：docs/recon/tencent.md

列表接口为公开 JSON，含职责描述；岗位要求需逐个请求详情接口，暂不抓取（requirements 留空）。
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job

LIST_URL = "https://careers.tencent.com/tencentcareer/api/post/Query"
PAGE_SIZE = 50


@register
class TencentAdapter(Adapter):
    id = "tencent"

    def fetch_raw(self) -> Iterator[dict]:
        page = 1
        while True:
            data = self.request_json("GET", LIST_URL, params={
                "pageIndex": page, "pageSize": PAGE_SIZE, "language": "zh-cn", "area": "cn",
            })
            body = data.get("Data") or {}
            posts = body.get("Posts") or []
            if data.get("Code") != 200:
                raise RuntimeError(f"tencent api code={data.get('Code')}")
            yield from posts
            total = body.get("Count") or 0
            if not posts or page * PAGE_SIZE >= total:
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def normalize(self, raw: dict) -> Job:
        if not raw.get("PostId") or not raw.get("RecruitPostName") or raw.get("IsValid") is False:
            raise SkipRecord
        url = (raw.get("PostURL") or "").replace("http://", "https://", 1)
        if not url:
            url = f"https://careers.tencent.com/jobdesc.html?postId={raw['PostId']}"
        city = (raw.get("LocationName") or "").strip()
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw["PostId"]),
            company=self.source.company,
            url=url,
            title=raw["RecruitPostName"].strip(),
            recruit_type="social",
            cities=[city] if city else [],
            department=raw.get("BGName") or None,
            description=raw.get("Responsibility") or None,
        )
