"""用户本地数据的位置、下载地址、打开方式与结果包装。CLI 与 MCP 共用。"""

import os
from pathlib import Path

from jobradar.core import queries as q
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts, parse_ts

REPO = "lijiaqimun-coder/job_radar"
RELEASE_TAG = "data-latest"
DB_FILES = {"jobs": "jobs.db", "text": "jd_text.db"}
STALE_HOURS = 48


class NoData(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("JOBRADAR_HOME", Path.home() / ".cache" / "jobradar"))


def release_url(name: str) -> str:
    base = f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{name}"
    mirror = os.environ.get("JOBRADAR_MIRROR", "").rstrip("/")  # 例如国内 GitHub 加速前缀
    return f"{mirror}/{base}" if mirror else base


def open_db(kind: str, required: bool = True):
    path = home() / DB_FILES[kind]
    if not path.exists():
        if required:
            raise NoData(f"本地没有数据：{path}。先运行 `jobradar update`。")
        return None
    return connect(path, kind)


def envelope(conn, results, **extra) -> dict:
    as_of = q.data_as_of(conn)
    stale = as_of is None or (parse_ts(now_ts()) - parse_ts(as_of)).total_seconds() > STALE_HOURS * 3600
    return {"data_as_of": as_of, "stale": stale, **extra, "results": results}
