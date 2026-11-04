"""帆软招聘站（`join.fanruan.com`）—— 官网前端使用的分页 JSON。

2026-11-04复核：当前前端POST JSON到/api/search.php，type为校招1/社招2/实习3，
筛选条件使用数组。历史回放可显式选择legacy契约，不在网络错误时自动退回旧接口。

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
PATH_CODES = {"campus": 1, "social": 2, "trainee": 3}

_MODE = {"社招": "social", "校招": "campus", "实习": "intern",
         "校园招聘": "campus", "实习生": "intern"}


@register
class FanruanAdapter(Adapter):
    id = "fanruan"

    def _headers(self, path: str) -> dict[str, str]:
        # 缺 `X-Requested-With` 会直接回整页 HTML（不是 JSON）；Referer 必须与请求 URL 一致。
        return {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": ("application/x-www-form-urlencoded; charset=UTF-8"
                             if self.source.params.get('api_style') == 'legacy' else 'application/json'),
            "Referer": f"{BASE}/{path}",
        }

    def _page(self, path: str, page: int) -> dict:
        if self.source.params.get('api_style') != 'legacy':
            if path not in PATH_CODES:
                raise RuntimeError('帆软招聘类型入口无效')
            return self.request_json('POST', BASE + '/api/search.php',
                json={'type': PATH_CODES[path], 'job_cate': [], 'types': [], 'departs': [], 'citys': [], 'page': page, 'w': ''},
                headers=self._headers(path))
        url = f"{BASE}/{path}"
        return self.request_json("POST", url, data={**FORM, "page": page},
                                 headers=self._headers(path))

    def fetch_raw(self) -> Iterator[dict]:
        paths = self.source.params.get("paths") or ["social", "campus", "trainee"]
        for path in paths:
            page, seen = 1, set()
            while True:
                data = self._page(path, page)
                if not isinstance(data, dict) or not isinstance(data.get('list'), list):
                    raise RuntimeError('帆软列表结构不完整')
                try:
                    total = int(data['pageTotal'])
                    current = int(data.get('curPage', page))
                    count = int(data['dataTotal']) if 'dataTotal' in data else None
                except (KeyError, ValueError, TypeError) as error:
                    raise RuntimeError('帆软分页信息无效') from error
                items = data['list']
                if (total < 0 or current != page or type(data['pageTotal']) is bool
                        or any(not isinstance(it, dict) or not it.get('id') or not it.get('job_name') for it in items)):
                    raise RuntimeError('帆软分页记录不完整')
                if not items:
                    if page != 1 or total > 1 or count != 0:
                        raise RuntimeError('帆软列表中途为空')
                    break
                ids = {str(it['id']) for it in items}
                if len(ids) != len(items) or seen.intersection(ids):
                    raise RuntimeError('帆软列表重复分页')
                seen.update(ids)
                for it in items:
                    rec = dict(it)
                    rec["_path"] = path
                    yield rec
                if page >= total:
                    if count is not None and len(seen) < count:
                        raise RuntimeError('帆软列表条数不足')
                    break
                if self.source.max_pages and page >= self.source.max_pages:
                    break
                page += 1

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
