from datetime import UTC, datetime

FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_ts() -> str:
    return datetime.now(UTC).strftime(FMT)


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, FMT).replace(tzinfo=UTC)
