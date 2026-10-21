"""腾讯招聘（社招）careers.tencent.com。侦察：docs/recon/tencent.md

列表接口为公开 JSON，含职责描述；岗位要求逐个请求详情接口 ByPostId（公开 JSON，约 2300 次/天，1 req/s）。

source.params:
  page_size: 每页条数，默认 50（录 fixtures 时用小值）
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job

LIST_URL = "https://careers.tencent.com/tencentcareer/api/post/Query"
DETAIL_URL = "https://careers.tencent.com/tencentcareer/api/post/ByPostId"
PAGE_SIZE = 50


@register
class TencentAdapter(Adapter):
    id = "tencent"

    def fetch_raw(self) -> Iterator[dict]:
        size = int(self.source.params.get("page_size", PAGE_SIZE))
        page = 1
        while True:
            data = self.request_json("GET", LIST_URL, params={
                "pageIndex": page, "pageSize": size, "language": "zh-cn", "area": "cn",
            })
            body = data.get("Data") or {}
            posts = body.get("Posts") or []
            if data.get("Code") != 200:
                raise RuntimeError(f"tencent api code={data.get('Code')}")
            for post in posts:
                yield {**post, "Requirement": self._requirement(post.get("PostId"))}
            total = body.get("Count") or 0
            if not posts or page * size >= total:
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def _requirement(self, post_id) -> str | None:
        if not post_id:
            return None
        d = self.request_json("GET", DETAIL_URL, params={"postId": post_id, "language": "zh-cn"})
        return (d.get("Data") or {}).get("Requirement") if d.get("Code") == 200 else None

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
            requirements=raw.get("Requirement") or None,
        )
