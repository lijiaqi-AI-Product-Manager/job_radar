from datetime import UTC, datetime, timedelta, timezone

FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_ts() -> str:
    return datetime.now(UTC).strftime(FMT)


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, FMT).replace(tzinfo=UTC)


def shanghai_date(ts: str) -> str:
    """招聘截止日按北京时间的自然日比较，记录时间仍统一为 UTC。"""
    return parse_ts(ts).astimezone(timezone(timedelta(hours=8))).date().isoformat()
