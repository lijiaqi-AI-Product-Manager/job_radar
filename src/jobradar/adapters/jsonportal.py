"""自建 SPA 招聘门户适配器：只认「前端直接调公开 JSON 接口、无签名、无 token」的那一类。

为什么单开一个适配器而不是每家公司写一份：这类站（vue/react 打包 + `/assets/index-*.js` +
一个返回明文 JSON 的分页接口）在国内央企/集团里非常常见，实测中国电子
（`campus.cec.com.cn`）就是 Vue3 + `/student-api/api/position/search`，
返回分页 records、`closeDate` 截止日、`cityName` 城市、`jobDescription`/`jobRequirements` 两段 JD，
一个 cookie 都不用带。它们的共同点只有「接口路径 + 字段名」，所以做成**配置驱动的通用适配器**。

红线：
  - 只读公开接口，请求体就是门户自己前端发的那个（不带任何签名/加密字段）；
  - `robots.txt` 与合规登记在 source.params/compliance 里逐站写清；
  - 接口必须**匿名可调**（不带 cookie、不带 referer 也能拿到数据），否则不使用本适配器。

source.params:
  base        : 接口根，如 "https://campus.cec.com.cn/student-api/api/position/search"
  method      : GET/POST，默认 POST
  page_param  : 页码字段名，默认 pageNum（从 1 开始）
  size_param  : 每页字段名，默认 pageSize
  page_size   : 每页条数，默认 50
  list_path   : 从响应 JSON 里取列表的路径（点号分隔，支持数组下标），如 data.records
  total_path  : 总数路径，如 data.total
  type_param  : 招聘类型字段名 + 取值映射，如 {positionType: {campus: 0, social: 1, intern: 2}}
  fields      : 字段映射 {title,city,description,requirement,deadline,org,code,recruit_hint}
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, date_only, grad_year_from_text


def _dig(obj, path: str):
    """按 `a.b.0.c` 取值；任一层缺就返回 None。"""
    cur = obj
    for part in (path or "").split("."):
        if not part:
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


@register
class JsonPortalAdapter(Adapter):
    id = "jsonportal"

    def _p(self, key, default=None):
        return self.source.params.get(key, default)

    def fetch_raw(self) -> Iterator[dict]:
        base = self._p("base")
        method = str(self._p("method", "POST")).upper()
        page_param = self._p("page_param", "pageNum")
        size_param = self._p("size_param", "pageSize")
        size = int(self._p("page_size", 50))
        type_param = self._p("type_param") or {}
        # 一个门户常常按类型分接口参数（0=校招 1=社招 2=内部），我们只取自己支持的类型，
        # 每种类型各翻一遍；没有 type_param 就只翻一遍（全量）。
        type_field = next(iter(type_param), None)
        type_values = (type_param.get(type_field) or {}) if type_field else {}
        wanted = [t for t in self.source.recruit_types if t in type_values] or (
            [None] if not type_field else [])
        if type_field and not wanted:
            return
        seen: set[str] = set()
        for rtype in wanted:
            page = 1
            while True:
                # 门户前端还会带一批固定字段（关键词、学历、机构过滤），服务端对缺字段的
                # 请求容忍度不一致，所以按站点配置原样带上，不猜默认值。
                body = dict(self._p("extra_body") or {})
                body[page_param] = page
                body[size_param] = size
                if type_field:
                    body[type_field] = type_values[rtype]
                if method == "GET":
                    data = self.request_json("GET", base, params=body)
                else:
                    data = self.request_json("POST", base, json=body)
                items = _dig(data, self._p("list_path", "data.records")) or []
                total = int(_dig(data, self._p("total_path", "data.total")) or 0)
                # 服务端会把每页条数压到自己的上限（实测中国电子 50 → 10 条/页），
                # 所以翻页不能按「page*size >= total」算，否则第 1 页就以为翻完了。
                # 优先用响应里真正的页码/页数（current/pages），没有才退回按条数累计。
                cur = int(_dig(data, self._p("page_path")) or page)
                pages = int(_dig(data, self._p("pages_path")) or 0)
                if not items:
                    break
                for it in items:
                    key = str(it.get(self._p("fields", {}).get("code") or "id") or "")
                    if key and key in seen:
                        continue
                    seen.add(key)
                    it = dict(it)
                    it["__recruit_type"] = rtype
                    yield it
                if pages:
                    done = cur >= pages
                else:
                    done = page * min(size, len(items)) >= total
                if done or page >= int(self._p("max_pages", 200)):
                    break
                page += 1

    def normalize(self, raw: dict) -> Job:
        f = self._p("fields") or {}
        title = str(raw.get(f.get("title", "name")) or "").strip()
        if not title:
            raise SkipRecord
        rtype = raw.get("__recruit_type") or (
            "campus" if self.source.recruit_types[0] == "campus" else self.source.recruit_types[0])
        city_raw = str(raw.get(f.get("city", "cityName")) or "").strip()
        # 城市字段常见写法：「深圳」「深圳/东莞」「深圳市·南山区」。只取第一个行政市名，
        # 不做拼音/别名映射——映射表在 normalize 模块里，这里保持"接口给什么写什么"。
        cities: list[str] = []
        for part in re.split(r"[/、,，]|\s+", city_raw):
            part = re.sub(r"(市|地区|特别行政区)$", "", part.strip())
            if 2 <= len(part) <= 8 and part not in cities:
                cities.append(part)
        desc = str(raw.get(f.get("description", "jobDescription")) or "").strip()
        req = str(raw.get(f.get("requirement", "jobRequirements")) or "").strip()
        deadline = date_only(raw.get(f.get("deadline", "closeDate")))
        grad = grad_year_from_text(title) if rtype != "social" else None
        org = str(raw.get(f.get("org", "org")) or "").strip() or None
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw.get(f.get("code", "id")) or raw.get("id") or ""),
            title=title,
            company=org or self.source.company,
            cities=cities,
            recruit_type=rtype,
            grad_year=grad,
            batch=batch_from_text(title) if rtype == "campus" else None,
            description=desc or None,
            requirements=req or None,
            apply_end=deadline,
            publish_at=date_only(raw.get(f.get("publish", "publishDate"))),
            url=(str(self._p("detail_url", "")).format(id=raw.get("id")) or None),
            department=str(raw.get(f.get("dept", "positionSecondOrg")) or "") or None,
        )
