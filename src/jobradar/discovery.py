"""从公开招聘日程提取最小事实与原始链接；发现线索不等于验证覆盖。"""

import json
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

NOWCODER_SCHEDULE = "https://www.nowcoder.com/jobs/school/schedule?type=0"


def _public_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
        return None
    if any(any(secret in key.lower() for secret in ("token", "session", "password", "ticket", "signature"))
           for key in parse_qs(url.query)):
        return None
    return value


def _day(milliseconds: object) -> str | None:
    if isinstance(milliseconds, bool) or not isinstance(milliseconds, (int, float)) or milliseconds <= 0:
        return None
    try:
        stamp = datetime.fromtimestamp(milliseconds / 1000, UTC).astimezone(timezone(timedelta(hours=8)))
        return stamp.date().isoformat() if 2000 <= stamp.year <= 2100 else None
    except (ValueError, OverflowError, OSError):
        return None


def parse_nowcoder_schedule(html: str) -> dict:
    marker = "window.__INITIAL_STATE__="
    if marker not in html:
        raise ValueError("公开页面没有招聘日程 JSON，可能改版或返回了挑战页")
    try:
        state, _ = json.JSONDecoder().raw_decode(html.split(marker, 1)[1].lstrip())
    except ValueError as exc:
        raise ValueError("招聘日程载荷不是可直接读取的 JSON，不执行页面脚本") from exc
    if not isinstance(state, dict) or not isinstance(state.get("app"), dict):
        raise ValueError("招聘日程载荷缺少 app 数据")
    schedule = next((app["scheduleData"] for app in state["app"].values()
                     if isinstance(app, dict) and isinstance(app.get("scheduleData"), dict)), None)
    if schedule is None or not isinstance(schedule.get("datas"), list):
        raise ValueError("招聘日程载荷缺少 scheduleData.datas")
    leads = []
    for row in schedule["datas"]:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
            continue
        company_id = row.get("companyId")
        if isinstance(company_id, bool) or not str(company_id).isdigit():
            continue
        ad = row.get("adInfo") if isinstance(row.get("adInfo"), dict) else {}
        url = _public_url(row.get("customWangshenLink")) or _public_url(ad.get("rawUrl"))
        cities = row.get("cityList") if isinstance(row.get("cityList"), list) else []
        leads.append({
            "company": row["name"].strip(), "company_id": str(company_id),
            "cities": list(dict.fromkeys(c.strip() for c in cities if isinstance(c, str) and c.strip())),
            "careers_url": url, "apply_start": _day(row.get("wangshenBeginDate")),
            "apply_end": _day(row.get("wangshenEndDate")), "batch": row.get("batchName"),
            "source_url": NOWCODER_SCHEDULE, "source_kind": "aggregator", "ownership_verified": False,
        })
    return {"current_page": schedule.get("currentPage"), "total_pages": schedule.get("totalPage"),
            "leads": leads}
