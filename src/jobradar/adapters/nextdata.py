"""Next.js 招聘页（内嵌 `__NEXT_DATA__` JSON）适配器。

为什么值得单独做一个适配器：这类站点的岗位**全在页面里的 `<script id="__NEXT_DATA__">`**
（服务端渲染时塞进去的 props），正文不需要任何前端执行就能拿到，而且结构比手写 HTML 稳定
——岗位是对象、职责/要求是数组，不用靠 `<h3>` 和关键字猜边界。

2026-10-27 从「官网 → 招聘入口」扫描里发现：豆瓣阅读（careers.arkread.com）就是这套结构，
`props.pageProps.jobList` 里 24 个岗位、每个岗位的 `content` 按「职位描述 / 职位要求」分组。

source.params:
  base_url: 招聘页 URL（必填）
  jobs_path: 到岗位数组的点路径，默认 "props.pageProps.jobList"
  title_key / desc_key / req_key / id_key / open_key / content_name_key：
      字段名，默认 title / content / requirements / id / isOpen / name
  desc_names / req_names：`content` 里哪几组的 name 算职责、哪几组算要求（默认按中文名匹配）
  job_url: 岗位详情链接模板，可选（站内没有单岗位 URL 时不写）
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import cities_from_text, grad_year_from_text

NEXT_DATA = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)

DESC_NAMES = ("职位描述", "岗位职责", "工作职责", "职责描述", "工作内容")
REQ_NAMES = ("职位要求", "任职要求", "任职资格", "岗位要求", "优先条件", "加分项")


def dig(obj, path: str):
    """按点路径取嵌套值；取不到返回 None。"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


@register
class NextdataAdapter(Adapter):
    id = "nextdata"

    def _params(self) -> dict:
        return self.source.params

    def fetch_raw(self) -> Iterator[dict]:
        p = self._params()
        html = self.request_text("GET", p["base_url"])
        m = NEXT_DATA.search(html)
        if not m:
            raise RuntimeError(f"{p['base_url']} 页面里没有 __NEXT_DATA__，可能已改版")
        data = json.loads(m.group(1))
        jobs = dig(data, p.get("jobs_path", "props.pageProps.jobList"))
        if not isinstance(jobs, list):
            raise RuntimeError(f"jobs_path={p.get('jobs_path')} 取到的不是数组")
        for j in jobs:
            if not isinstance(j, dict):
                continue
            yield j

    def normalize(self, raw: dict) -> Job:
        # 注意：`isOpen` 在豆瓣阅读这类站点上**不可靠**（实测 24 个岗位里 22 个标 False，
        # 但职责/要求正文全都齐全，页面也在正常展示），所以默认不按它过滤。
        # 真要按状态过滤就显式配 params.drop_closed: true。
        _ = raw
        p = self._params()
        title = str(raw.get(p.get("title_key", "title")) or "").strip()
        if not title:
            raise SkipRecord("没有标题")
        if p.get("drop_closed") and p.get("open_key", "isOpen") in raw \
                and raw[p.get("open_key", "isOpen")] is False:
            raise SkipRecord("站点标记为不开放（drop_closed=true）")
        groups = raw.get(p.get("desc_key", "content")) or []
        name_key = p.get("content_name_key", "name")
        desc: list[str] = []
        req: list[str] = []
        for g in groups if isinstance(groups, list) else []:
            if not isinstance(g, dict):
                continue
            name = str(g.get(name_key) or "")
            items = g.get("items") or []
            body = "\n".join(str(x).strip() for x in items if str(x).strip())
            if not body:
                continue
            if any(w in name for w in REQ_NAMES):
                req.append(body)
            elif any(w in name for w in DESC_NAMES):
                desc.append(body)
            else:
                # 名字对不上就归到职责——宁可多写职责，不要把正文丢掉
                desc.append(body)
        url = p.get("base_url")
        if p.get("job_url") and raw.get(p.get("id_key", "id")):
            url = p["job_url"].format(id=raw[p.get("id_key", "id")])
        return Job(
            source_id=self.source.id,
            source_job_id=str(raw.get(p.get("id_key", "id")) or title)[:80],
            company=self.source.company,
            url=url,
            title=title,
            recruit_type=p.get("recruit_type", "social"),
            cities=cities_from_text(raw.get(p.get("city_key", "city"))),
            grad_year=grad_year_from_text(title),
            description="\n".join(desc) or None,
            requirements="\n".join(req) or None,
        )
