"""腾讯校园招聘 join.qq.com（应届生/实习生）。侦察：docs/recon/tencent.md §9

列表接口（POST，公开 JSON）只有标题、城市、事业群；职责与要求逐岗位请求详情接口（GET，公开 JSON）。
约 1000 岗，按 1 req/s 每日约 17 分钟。
青云课题类岗位的 desc/request 为空，JD 在 topicDetail/topicRequirement；
列表里仍有、详情返回"岗位已下架"（status 404）的岗位跳过。

source.params:
  page_size: 每页条数，默认 100（录 fixtures 时用小值）
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, cities_from_text, grad_year_from_text

LIST_URL = "https://join.qq.com/api/v1/position/searchPosition"
DETAIL_URL = "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId"
DETAIL_KEYS = ("desc", "request", "topicDetail", "topicRequirement", "tidName")
JOB_URL = "https://join.qq.com/post_detail.html?postid={id}"
PAGE_SIZE = 100


def recruit_type_of(project: str) -> str | None:
    """项目名即招聘类型：应届毕业生、青云计划-应届生 → campus；应届实习、项目实习生 → intern。"""
    if "实习" in project:
        return "intern"
    if "应届" in project or "毕业" in project:
        return "campus"
    return None


@register
class TencentCampusAdapter(Adapter):
    id = "tencent_campus"

    def fetch_raw(self) -> Iterator[dict]:
        size = int(self.source.params.get("page_size", PAGE_SIZE))
        page = 1
        while True:
            data = self.request_json("POST", LIST_URL, json={
                "projectIdList": [], "projectMappingIdList": [], "keyword": "", "bgList": [],
                "workCountryType": 0, "workCityList": [], "recruitCityList": [], "positionFidList": [],
                "pageIndex": page, "pageSize": size,
            })
            if data.get("status") != 0:
                raise RuntimeError(f"tencent campus api status={data.get('status')}")
            body = data.get("data") or {}
            items = body.get("positionList") or []
            for item in items:
                detail, delisted = {}, False
                if item.get("postId"):
                    d = self.request_json("GET", DETAIL_URL, params={"postId": item["postId"]})
                    detail = (d.get("data") or {}) if d.get("status") == 0 else {}
                    delisted = d.get("status") == 404 and "下架" in (d.get("message") or "")
                yield {**item, "delisted": delisted, "detail": {k: detail.get(k) for k in DETAIL_KEYS}}
            total = body.get("count") or 0
            if not items or page * size >= total:
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def normalize(self, raw: dict) -> Job:
        recruit_type = recruit_type_of(raw.get("projectName") or raw.get("recruitLabelName") or "")
        if not raw.get("postId") or not raw.get("positionTitle") or recruit_type is None or raw.get("delisted"):
            raise SkipRecord
        title = raw["positionTitle"].strip()
        cities: list[str] = []
        for name in (raw.get("workCities") or "").split():
            for c in cities_from_text(name.removesuffix("总部")):
                if c not in cities:
                    cities.append(c)
        detail = raw.get("detail") or {}
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw["postId"]),
            company=self.source.company,
            url=JOB_URL.format(id=raw["postId"]),
            title=title,
            recruit_type=recruit_type,
            grad_year=grad_year_from_text(title),
            batch=batch_from_text(title) if recruit_type == "campus" else None,
            cities=cities,
            department=" ".join((raw.get("bgs") or "").split()) or None,
            description=detail.get("desc") or detail.get("topicDetail") or None,
            requirements=detail.get("request") or detail.get("topicRequirement") or None,
        )
