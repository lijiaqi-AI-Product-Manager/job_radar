"""京东校招 campus.jd.com（TGT 天才计划 / JDS 新星 / TET 管培 / 实习计划）。

两个接口，都**必须**用 `campus.jd.com` 这个域名：

1. `GET  /api/wx/position/getProjectList`            -> 招聘项目字典（planId 就来自这里）
2. `POST /api/wx/position/page?type={type}`          -> 岗位分页

type 与 planId 的对应关系来自 1（本项目自己不再硬编码 planId）：

| type         | 含义     | planId                          |
|--------------|----------|---------------------------------|
| `talent`     | TGT 专项 | 47 TGT 技术天才 / 55 TGT 实习    |
| `present`    | 应届生   | 56 JDS 新星 / 57 TET 管培 / 58 新锐之星 |
| `internship` | 实习生   | 45 JD YOUNG / 51 新锐之星实习    |

2026-10-26 实测的坑：

1. **域名是决定性的**。`zhaopin.jd.com` 的同名接口会 302 到
   `passport.jd.com/new/login.aspx`（登录墙），而 `campus.jd.com` 同一路径 200 直出。
   请求要带 `Referer: https://campus.jd.com/`（浏览器同源请求本来就会带）。
2. **`pageIndex` 从 0 开始**（不是 1），且响应里 `pageCount` 恒为 0，只有 `totalNumber` 可信。
3. **筛选参数名是 `positionDeptList`** 不是 `deptCodeList`；写错时 Tomcat 直接 400 HTML，
   不是 JSON 报错，很容易误判成"接口挂了"。
4. `publishTime` 是**毫秒时间戳**（`1784814564000`），交给 `date_only()` 归一。
5. 城市不在岗位上，在 `requirementVoList[].workCity`（"重庆市-重庆市" 这种"省-市"格式），
   一个岗位可能有多个需求城市 → 取并集。

source.params:
  page_size: 每页条数，默认 50
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, cities_from_text, date_only, grad_year_from_text

BASE = "https://campus.jd.com"
PROJECT_URL = f"{BASE}/api/wx/position/getProjectList"
PAGE_URL = f"{BASE}/api/wx/position/page"
JOB_URL = f"{BASE}/#/job/detail/{{id}}"
REFERER = f"{BASE}/"
PAGE_SIZE = 50
# type -> recruit_type。talent 里的 55 是"TGT 技术实习生"，所以 talent 不能整包算校招，
# 由 planName 里是否含"实习"决定；present 一定是校招，internship 一定是实习。
TYPE_RECRUIT = {"talent": "campus", "present": "campus", "internship": "intern"}


@register
class JdAdapter(Adapter):
    id = "jd"

    def _post(self, url: str, body: dict) -> dict:
        data = self.request_json("POST", url, json=body, headers={"Referer": REFERER})
        if not data.get("success"):
            raise RuntimeError(f"jd {url.split('?')[0]}: success=false msg={data.get('message')}")
        return data.get("body") or {}

    def _plans(self) -> list[dict]:
        """拉项目字典，返回 [{type, planId, planName}]。"""
        data = self.request_json("GET", PROJECT_URL, headers={"Referer": REFERER})
        # 字典接口失败时必须报错：静默当成"没有项目"会让上层显示"抓到 0 条"，
        # 看起来像京东没在校招，实际是被挡了/接口改了。
        if not data.get("success"):
            raise RuntimeError(f"jd getProjectList: success=false msg={data.get('message')}")
        body = data.get("body") or {}
        out: list[dict] = []
        for proj in body.get("projectList") or []:
            ptype = proj.get("code")
            if not proj.get("release", True) or ptype not in TYPE_RECRUIT:
                continue
            for group in proj.get("groupList") or []:
                for pm in group.get("planMapList") or []:
                    if pm.get("id") is not None:
                        out.append({"type": ptype, "planId": pm["id"], "planName": pm.get("planName") or ""})
        return out

    def fetch_raw(self) -> Iterator[dict]:
        size = int(self.source.params.get("page_size", PAGE_SIZE))
        seen_plans: set[tuple[str, int]] = set()
        for plan in self._plans():
            key = (plan["type"], plan["planId"])
            if key in seen_plans:
                continue
            seen_plans.add(key)
            page = 0  # pageIndex 从 0 开始
            seen_ids: set[str] = set()
            while True:
                body = self._post(PAGE_URL + f"?type={plan['type']}", {
                    "pageSize": size, "pageIndex": page,
                    "parameter": {"positionName": "", "planIdList": [plan["planId"]],
                                  "jobDirectionCodeList": [], "workCityCodeList": [], "positionDeptList": []},
                })
                items = body.get("items") or []
                if not items:
                    break  # 空页只结束当前项目，其它项目继续
                # 自检：分页一旦失效，服务端会重复返回同一页。靠 publishId 去重让重复页变成空转并停下
                # （百度那边真踩过：分页参数放错位置，16 次翻页拿到同一页，694 条抓成 20 条）。
                fresh = [it for it in items if str(it.get("publishId")) not in seen_ids]
                if not fresh:
                    break
                for it in fresh:
                    seen_ids.add(str(it.get("publishId")))
                    yield {**it, "_type": plan["type"], "_plan": plan["planName"]}
                try:
                    total = int(body.get("totalNumber") or 0)
                except (TypeError, ValueError):
                    total = 0
                if (page + 1) * size >= total:
                    break
                if self.source.max_pages and page + 1 >= self.source.max_pages:
                    break
                page += 1

    def normalize(self, raw: dict) -> Job:
        pid = raw.get("publishId")
        title = (raw.get("positionName") or "").strip()
        if pid is None or not title:
            raise SkipRecord
        ptype = raw["_type"]
        plan = raw["_plan"] or ""
        # TGT 专项里 55 是"技术实习生"，不能跟着 talent 一起算校招
        recruit = "intern" if "实习" in plan else TYPE_RECRUIT[ptype]
        cities: list[str] = []
        for req in raw.get("requirementVoList") or []:
            for c in cities_from_text(req.get("workCity")):
                if c not in cities:
                    cities.append(c)
        for c in cities_from_text(raw.get("workCity")):
            if c not in cities:
                cities.append(c)
        direction = (raw.get("jobDirection") or "").strip() or None
        return Job(
            source_id=self.source.id,
            source_job_id=str(pid),
            company=self.source.company,
            url=JOB_URL.format(id=pid),
            title=title,
            recruit_type=recruit,
            subcategory=direction,   # "采销与物流方向" 这类是京东自己的方向名
            grad_year=grad_year_from_text(title, loose=recruit != "social"),
            batch=batch_from_text(plan) or batch_from_text(title),
            cities=cities,
            # publishTime 是毫秒时间戳
            publish_at=date_only(raw.get("publishTime")),
            description=(raw.get("workContent") or "").strip() or None,
            requirements=(raw.get("qualification") or "").strip() or None,
        )
