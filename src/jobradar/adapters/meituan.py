"""美团招聘 zhaopin.meituan.com（校招/实习/社招）。侦察：docs/recon/meituan.md

列表接口为公开 JSON（POST，无需登录），每条已含岗位职责与要求，无需请求详情。
jobType：1 校招、2 实习、3 社招；请求时 jobType 传空列表即返回全部三类。

source.params:
  page_size: 每页条数，默认 100（录 fixtures 时用小值）
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, cities_from_text, date_only, grad_year_from_text

LIST_URL = "https://zhaopin.meituan.com/api/official/job/getJobList"
JOB_URL = "https://zhaopin.meituan.com/web/position/detail?jobUnionId={id}&highlightType={portal}"
PAGE_SIZE = 100
RECRUIT_TYPE = {"1": "campus", "2": "intern", "3": "social"}
PORTAL = {"campus": "campus", "intern": "campus", "social": "social"}


@register
class MeituanAdapter(Adapter):
    id = "meituan"

    def fetch_raw(self) -> Iterator[dict]:
        size = int(self.source.params.get("page_size", PAGE_SIZE))
        page = 1
        while True:
            data = self.request_json("POST", LIST_URL, json={
                "page": {"pageNo": page, "pageSize": size}, "jobShareType": "1", "keywords": "",
                "cityList": [], "department": [], "jfJgList": [], "jobType": [], "typeCode": [], "specialCode": [],
            })
            body = data.get("data")
            if not isinstance(body, dict):
                raise RuntimeError(f"meituan api: unexpected response {str(data)[:200]}")
            items = body.get("list") or []
            yield from items
            total_pages = (body.get("page") or {}).get("totalPage") or 0
            if not items or page >= total_pages:
                return
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def normalize(self, raw: dict) -> Job:
        recruit_type = RECRUIT_TYPE.get(str(raw.get("jobType")))
        if not raw.get("jobUnionId") or not raw.get("name") or recruit_type is None:
            raise SkipRecord
        title = raw["name"].strip()
        cities: list[str] = []
        for c in raw.get("cityList") or []:
            for name in cities_from_text((c or {}).get("name")):
                if name not in cities:
                    cities.append(name)
        depts = [d.get("name") for d in raw.get("department") or [] if isinstance(d, dict) and d.get("name")]
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw["jobUnionId"]),
            company=self.source.company,
            url=JOB_URL.format(id=raw["jobUnionId"], portal=PORTAL[recruit_type]),
            title=title,
            recruit_type=recruit_type,
            grad_year=grad_year_from_text(title) if recruit_type != "social" else None,
            batch=batch_from_text(title) if recruit_type == "campus" else None,
            cities=cities,
            department="/".join(depts) or None,
            description=raw.get("jobDuty") or None,
            requirements=raw.get("jobRequirement") or None,
            # 列表接口直接给了三个日期，抓到就是白拿的（2026-10-26 实测）：
            #   firstPostTime 首次发布 —— 多数岗位为 null，有值就是真正的上架日
            #   refreshTime   最近刷新 —— 实测当天刷新的岗位就是这个时刻（1792991700000 = 13:15）
            #   expiredTime   截止日   —— 常为 null（不限），有值即截止
            # 用 firstPostTime 优先，缺失时退回 refreshTime：刷新日只会晚于真实上架日，
            # 拿它当"上架日"会把窗口报窄，但比留空更能解释"这批什么时候开的"。
            publish_at=date_only(raw.get("firstPostTime") or raw.get("refreshTime")),
            apply_end=date_only(raw.get("expiredTime")),
        )
