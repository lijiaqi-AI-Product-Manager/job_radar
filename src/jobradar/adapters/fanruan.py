"""帆软招聘站（`join.fanruan.com`）—— WordPress 主题自带的分页 JSON。

侦察记录（2026-10-27 实测）：门户是 WordPress，但它把岗位列表做成了
**「POST 请求当前页面 URL 本身」**——URL 不变，只靠 `X-Requested-With` 与表单体区分：

  POST https://join.fanruan.com/{social|campus|trainee}
  body: filter=1&page=N&w=&types=&departs=&citys=&cv=
  headers: X-Requested-With: XMLHttpRequest + Referer: 同一 URL

返回 `{"list": [...], "pageTotal": 9, "curPage": 1, "dataTotal": "84"}`，
每条给全：`job_name / apartment(部门) / job_type(职类) / base(城市，逗号分隔) /
salary / mode(社招/校招/实习) / duty(职责) / requirement(要求)` —— **不需要详情页**。

`pageSize` 固定 10，服务端不认更大的值，只能翻页（9 页 = 9 个请求，1 rps 下 9 秒）。

source.params:
  paths: 要抓的页面路径，默认 `["social", "campus", "trainee"]`
"""

import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import categorize, grad_year_from_text

BASE = "https://join.fanruan.com"
FORM = {"filter": 1, "w": "", "types": "", "departs": "", "citys": "", "cv": ""}

_MODE = {"社招": "social", "校招": "campus", "实习": "intern",
         "校园招聘": "campus", "实习生": "intern"}


@register
class FanruanAdapter(Adapter):
    id = "fanruan"

    def _headers(self, path: str) -> dict[str, str]:
        # 缺 `X-Requested-With` 会直接回整页 HTML（不是 JSON）；Referer 必须与请求 URL 一致。
        return {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{BASE}/{path}",
        }

    def _page(self, path: str, page: int) -> dict:
        url = f"{BASE}/{path}"
        return self.request_json("POST", url, data={**FORM, "page": page},
                                 headers=self._headers(path))

    def fetch_raw(self) -> Iterator[dict]:
        paths = self.source.params.get("paths") or ["social", "campus", "trainee"]
        for path in paths:
            first = self._page(path, 1)
            total = int(first.get("pageTotal") or 1)
            for it in first.get("list") or []:
                rec = dict(it)
                rec["_path"] = path
                yield rec
            if self.source.max_pages:
                total = min(total, self.source.max_pages)
            for page in range(2, total + 1):
                data = self._page(path, page)
                for it in data.get("list") or []:
                    rec = dict(it)
                    rec["_path"] = path
                    yield rec

    def normalize(self, raw: dict) -> Job:
        jid = str(raw.get("id") or "").strip()
        title = str(raw.get("job_name") or "").strip()
        if not jid or not title:
            raise SkipRecord("缺少 id 或岗位名")
        mode = str(raw.get("mode") or "").strip()
        path = raw.get("_path") or ""
        rtype = _MODE.get(mode) or ("intern" if path == "trainee" else "campus" if path == "campus" else "social")
        # `base` 是「无锡, 南京」这种逗号串，可能带空格
        cities = [c.strip() for c in re.split(r"[,，/]", str(raw.get("base") or "")) if c.strip()]
        duty = str(raw.get("duty") or "").strip()
        req = str(raw.get("requirement") or "").strip()
        text = f"{title} {duty[:200]}"
        cat, sub = categorize(title)
        return Job(
            source_id=self.source.id,
            source_job_id=jid,
            company=self.source.company,
            url=f"{BASE}/job/{jid}" if raw.get("_path") != "trainee" else f"{BASE}/trainee",
            title=title,
            recruit_type=rtype,
            category=cat,
            subcategory=sub,
            grad_year=grad_year_from_text(text),
            cities=cities,
            department=str(raw.get("apartment") or "").strip() or None,
            description=duty or None,
            requirements=req or None,
        )
