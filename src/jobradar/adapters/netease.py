"""网易校园招聘（campus.163.com / campus.game.163.com）。侦察：docs/recon/netease.md

站点是 React SPA，但列表走公开 JSON：
`GET {base}/api/campuspc/position/getJobList?projectId=<id>&pageNo=1&pageSize=100`
列表直接含职责（positionDescription）与要求（positionRequirement）原文，无需详情请求。
无需登录、无签名、无验证码；易盾 SDK 只用于登录/报名。

已知限制：接口不返回单岗位 URL（分享接口只给微信 JS-SDK 签名），
`url` 用项目列表页，用户在该页按标题搜索。

source.params:
  base_url: 站点根（campus.163.com 或 campus.game.163.com）
  project_id: 招聘项目 id（应届生：网易互联网 103、网易互娱 102；蛋仔 AI 实习 75）
  project_name: 项目名，用于提取届别/批次（如「网易互联网2027届校园招聘」）——站点字段里没有届别
  page_size: 每页条数，默认 100（录 fixtures 时用小值）
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, cities_from_text, date_only, grad_year_from_text

LIST_PATH = "/api/campuspc/position/getJobList"
PAGE_SIZE = 100


@register
class NeteaseAdapter(Adapter):
    id = "netease"

    def _base(self) -> str:
        return self.source.params.get("base_url", "https://campus.163.com").rstrip("/")

    def fetch_raw(self) -> Iterator[dict]:
        project_id = self.source.params["project_id"]
        size = int(self.source.params.get("page_size", PAGE_SIZE))
        page = 1
        while True:
            data = self.request_json("GET", f"{self._base()}{LIST_PATH}",
                                     params={"projectId": project_id, "pageNo": page, "pageSize": size})
            if data.get("code") != 200:
                raise RuntimeError(f"netease project={project_id} code={data.get('code')} {data.get('msg')}")
            body = data.get("data") or {}
            items = body.get("list") or []
            yield from items
            pages = body.get("pages") or 0
            if not items or page >= pages:
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def normalize(self, raw: dict) -> Job:
        if not raw.get("id") or not (raw.get("positionName") or "").strip():
            raise SkipRecord
        project_name = self.source.params.get("project_name") or ""
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw["id"]),
            company=self.source.company,
            # 没有单岗位链接：落到项目列表页（docs/recon/netease.md §5）
            url=f"{self._base()}/app/job/position?id={self.source.params['project_id']}",
            title=raw["positionName"].strip(),
            recruit_type=self.source.recruit_types[0],
            grad_year=grad_year_from_text(project_name),
            batch=batch_from_text(project_name),
            cities=cities_from_text(raw.get("workPlaceName")),
            # updateTime 是"最近更新"（逐条不同、不是整站刷新），当最晚上架日，不当截止日
            publish_at=date_only(raw.get("updateTime")),
            description=(raw.get("positionDescription") or "").strip() or None,
            requirements=(raw.get("positionRequirement") or "").strip() or None,
        )
