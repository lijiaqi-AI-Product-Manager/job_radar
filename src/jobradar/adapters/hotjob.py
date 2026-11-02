"""hotjob（大易云）招聘门户：`{host}/wecruit/...`，平台型适配器。

侦察：docs/recon/hotjob.md。列表与详情都是公开 GET JSON（`iSaJAx=isAjax`），无需登录/签名。

source.params:
  tenant: 站点 id，如 "SU60a6449a2f9d2430fdc11a19"（页面 URL 第一段，必填）
  host: 默认 "wecruit.hotjob.cn"；自定义域名如 "yili.hotjob.cn"
  page_size: 请求的每页条数（服务端可能更小），默认 50
  fetch_detail: 是否逐岗请求详情拿 JD 正文，默认 True（契约要求 ≥90% 有正文）

已知：`recruitType` 1=校园、2=社招、3=实习；城市在 `workPlaceStr`（如「长沙市-长沙县」）。
"""

from collections.abc import Iterator
from datetime import timedelta

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.adapters.qualification import requirement_grad_year, uncertain_title_cohort
from jobradar.jd_text import template_pollution
from jobradar.models import Job
from jobradar.normalize import (
    batch_from_text,
    date_only,
    degree_min_from_text,
    grad_year_from_text,
    normalize_degree,
)
from jobradar.timeutil import now_ts, parse_ts

RECRUIT_CODE = {"campus": "1", "social": "2", "intern": "3"}
PORTAL = {"campus": "campus", "social": "social", "intern": "campus"}
DEFAULT_HOST = "wecruit.hotjob.cn"
DEFAULT_PAGE_SIZE = 50

# 大易对"长期开放"的岗位给 3000-01-01，是哨兵值不是真日期。
# 当成真日期会让"找快截止的岗位"筛出一堆 3000 年，必须归一成 None。
# （哨兵判定已收进 normalize.date_only，这里保留常量给文档引用）
_LONG_TERM_YEAR = 2100
# workPlaceStr 的「全部地区」「不限」也不是城市
_PLACE_NOISE = {"全部地区", "不限", "全国", "多个城市", "若干"}


def verified_detail_fields(requirement: str) -> dict:
    """已核验租户要求段中明确的单一届次和学历；调用方负责租户开关。"""
    return {"grad_year": requirement_grad_year(requirement),
            "degree_min": degree_min_from_text(requirement)}


def _date_only(s) -> str | None:
    """'2026-10-24 11:30:58' -> '2026-10-24'；空值/哨兵值/0001 年 -> None。"""
    return date_only(s)


def _cities_from_place(place: str | None) -> list[str]:
    """'长沙市-长沙县' -> ['长沙']；'北京' -> ['北京']；'全部地区' -> []。

    只取城市级（第一段），不要区县——用户按城市筛，区县会把结果切得太碎。
    逗号/顿号分隔的多个城市也拆开。
    """
    if not place or not isinstance(place, str):
        return []
    out: list[str] = []
    for chunk in place.replace("，", ",").replace("、", ",").replace("/", ",").split(","):
        seg = chunk.split("-")[0].strip()
        if not seg or seg in _PLACE_NOISE:
            continue
        seg = seg.removesuffix("市")
        if seg and seg not in out and len(seg) <= 12:
            out.append(seg)
    return out[:6]


@register
class HotjobAdapter(Adapter):
    id = "hotjob"

    @property
    def tenant(self) -> str:
        return self.source.params["tenant"]

    @property
    def host(self) -> str:
        return self.source.params.get("host", DEFAULT_HOST)

    def _params(self, **extra) -> dict:
        # 不加 	=<毫秒时间戳>：服务端不校验，但带随机参数会让 fixtures 无法回放
        return {"iSaJAx": "isAjax", "request_locale": "zh_CN", **extra}

    def _list(self, code: str, page: int) -> dict:
        return self.request_json(
            "GET", f"https://{self.host}/wecruit/positionInfo/listPosition/{self.tenant}",
            params=self._params(isFrompb="true", recruitType=code,
                                pageSize=str(int(self.source.params.get("page_size", DEFAULT_PAGE_SIZE))),
                                currentPage=str(page)),
            headers={"Referer": f"https://{self.host}/{self.tenant}/pb/social.html"},
        )

    def _detail(self, post_id: str) -> dict:
        data = self.request_json(
            "GET", f"https://{self.host}/wecruit/positionInfo/listPositionDetail/{self.tenant}",
            params=self._params(postId=post_id),
            headers={"Referer": f"https://{self.host}/{self.tenant}/pb/posDetail.html?postId={post_id}"},
        )
        return data.get("data") or {}

    def _cached_detail(self, item, recruit_type, *, allow_old=False):
        hours = self.source.params.get("detail_cache_hours", 0)
        if type(hours) is not int or not 0 < hours <= 168:
            return None
        cached = getattr(self, "cached_texts", {}).get(str(item.get("postId")))
        if not cached or cached.get("title") != (item.get("postName") or "").strip():
            return None
        if cached.get("recruit_type") != recruit_type or cached.get("publish_at") != _date_only(item.get("publishDate") or item.get("publishFirstDate")):
            return None
        if normalize_degree(cached.get("degree_min")) != normalize_degree(item.get("educationStr")):
            return None
        body = (cached.get("description"), cached.get("requirements"))
        if not any(body) or any(template_pollution(value) for value in body):
            return None
        try:
            observed = parse_ts(cached["fetched_at"])
            current = parse_ts(now_ts())
        except (ValueError, TypeError, KeyError):
            return None
        if observed > current or (not allow_old and current - observed > timedelta(hours=hours)):
            return None
        return {"workContent": body[0], "serviceCondition": body[1], "education": cached.get("degree_min")}, cached["fetched_at"]

    def fetch_raw(self) -> Iterator[dict]:
        fetch_detail = bool(self.source.params.get("fetch_detail", True))
        for rtype in self.source.recruit_types:
            code = RECRUIT_CODE[rtype]
            page = 1
            seen_pages = set()
            while True:
                data = self._list(code, page)
                inner = data.get("data") if isinstance(data, dict) else None
                form = inner.get("pageForm") if isinstance(inner, dict) else None
                if not isinstance(form, dict) or not isinstance(form.get("pageData"), list):
                    raise RuntimeError("hotjob invalid list page")
                items = form["pageData"]
                try:
                    total = int(form["totalPage"])
                except (ValueError, TypeError, KeyError) as exc:
                    raise RuntimeError("hotjob invalid pagination") from exc
                if not items:
                    if total != 0 or page != 1:
                        raise RuntimeError("hotjob incomplete empty page")
                    break
                if total < page or any(not isinstance(item, dict) or not item.get("postId") for item in items):
                    raise RuntimeError("hotjob incomplete list records")
                signature = tuple(str(item["postId"]) for item in items)
                if signature in seen_pages:
                    raise RuntimeError("hotjob repeated full page")
                seen_pages.add(signature)
                for it in items:
                    detail = {}
                    observed = None
                    if fetch_detail and it.get("postId"):
                        cached = self._cached_detail(it, rtype)
                        if cached:
                            detail, observed = cached
                        else:
                            try:
                                detail = self._detail(it["postId"])
                            except Exception:  # noqa: BLE001 — 列表完整时保留已有正文及其实际观测时间
                                fallback = self._cached_detail(it, rtype, allow_old=True)
                                if fallback:
                                    detail, observed = fallback
                    yield {"list": it, "detail": detail, "recruit_type": rtype, "text_observed_at": observed}
                if page >= total:
                    break
                if self.source.max_pages and page >= self.source.max_pages:
                    break
                page += 1

    def normalize(self, raw: dict) -> Job:
        it, detail = raw["list"], raw.get("detail") or {}
        post_id = it.get("postId")
        title = (it.get("postName") or "").strip()
        if not post_id or not title:
            raise SkipRecord
        rtype = raw["recruit_type"]
        cities = _cities_from_place(it.get("workPlaceStr"))
        uncertain = uncertain_title_cohort(title)
        year = grad_year_from_text(title, loose=True) if rtype != "social" and not uncertain else None
        degree = detail.get("education") or it.get("educationStr") or None
        if self.source.params.get("detail_fields"):
            # 仅对已核验并显式启用的租户读取要求段；不是全适配器通用 JD 届次回填。
            requirement = detail.get("serviceCondition") or ""
            fields = verified_detail_fields(requirement)
            if year is None and rtype != "social" and not uncertain:
                year = fields["grad_year"]
            if not degree:
                degree = fields["degree_min"]
        return Job(
            source_id=self.source.id,
            source_job_id=str(post_id),
            company=self.source.company,
            url=(f"https://{self.host}/{self.tenant}/pb/posDetail.html"
                 f"?postId={post_id}&postType={PORTAL[rtype]}"),
            title=title,
            recruit_type=rtype,
            grad_year=year,
            batch=batch_from_text(title) if rtype == "campus" else None,
            cities=cities,
            degree_min=degree,
            department=(it.get("company") or None),
            # 大易列表接口直接给了这两个日期，抓到就是白拿的截止日
            apply_end=_date_only(it.get("endDate")),
            publish_at=_date_only(it.get("publishDate") or it.get("publishFirstDate")),
            description=(detail.get("workContent") or None),
            requirements=(detail.get("serviceCondition") or None),
            text_observed_at=raw.get("text_observed_at"),
        )
