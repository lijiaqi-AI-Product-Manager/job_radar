"""【适配器模板】针对虚构站点 api.example.invalid 的完整参考实现。

新增适配器：复制本文件为 adapters/<id>.py，并同时复制
  tests/adapters/test_example.py  -> tests/adapters/test_<id>.py
  tests/fixtures/example/         -> tests/fixtures/<id>/（用 scripts/record_fixtures.py 录制真实响应）
然后只改下面标注 [改] 的地方。不要改变整体结构。

约定：
- fetch_raw 只做"翻页取数"，不做任何字段加工；normalize 只做"字段映射"，不做网络请求。
- 必须遵守 self.source.max_pages（录 fixtures 与测试时靠它限量）。
- 所有网络请求走 self.request_json（限速 + 重试）。
- 拿不准的字段留 None，不要猜。职类 category/subcategory 优先留空，由 taxonomy 归一化阶段处理。
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job

# [改] 站点特有的常量
LIST_URL = "https://api.example.invalid/v1/jobs"
JOB_URL = "https://careers.example.invalid/job/{id}"
PAGE_SIZE = 20
RECRUIT_TYPE = {"校招": "campus", "实习": "intern", "社招": "social"}


@register
class ExampleAdapter(Adapter):
    id = "example"  # [改] 与文件名一致

    def fetch_raw(self) -> Iterator[dict]:
        page = 1
        while True:
            data = self.request_json("GET", LIST_URL, params={"page": page, "size": PAGE_SIZE})
            items = data.get("items") or []
            if not items:
                return
            yield from items
            if self.source.max_pages and page >= self.source.max_pages:
                return
            page += 1

    def normalize(self, raw: dict) -> Job:
        if not raw.get("id") or not raw.get("title"):
            raise SkipRecord
        recruit_type = RECRUIT_TYPE.get(raw.get("type", ""))
        if recruit_type is None:
            raise SkipRecord
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw["id"]),
            company=self.source.company,
            url=JOB_URL.format(id=raw["id"]),
            title=raw["title"].strip(),
            recruit_type=recruit_type,
            grad_year=raw.get("grad_year"),
            batch=raw.get("batch"),
            cities=[c.strip() for c in (raw.get("city") or "").split("/") if c.strip()],
            degree_min=raw.get("degree"),
            department=raw.get("dept"),
            description=raw.get("desc"),
            requirements=raw.get("req"),
        )
