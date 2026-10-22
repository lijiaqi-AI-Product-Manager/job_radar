"""用户本地数据的位置、下载地址、打开方式与结果包装。CLI 与 MCP 共用。"""

import os
from contextlib import contextmanager
from pathlib import Path

from jobradar.core import queries as q
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts, parse_ts

REPO = "lijiaqimun-coder/job_radar"
GITEE_REPO = os.environ.get("JOBRADAR_GITEE_REPO", "qgauss/job_radar")  # 国内镜像（Gitee 发行版）
RELEASE_TAG = "data-latest"
DB_FILES = {"jobs": "jobs.db", "text": "jd_text.db", "calendar": "calendar.db"}
STALE_HOURS = 48


class NoData(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("JOBRADAR_HOME", Path.home() / ".cache" / "jobradar"))


def github_url(name: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{name}"


def gitee_url(name: str) -> str:
    return f"https://gitee.com/{GITEE_REPO}/releases/download/{RELEASE_TAG}/{name}"


def asset_urls(name: str, prefer: str | None = None) -> list[tuple[str, str]]:
    """按尝试顺序返回 (镜像名, 下载地址)。
    prefer：github / gitee；JOBRADAR_MIRROR 若是 URL 前缀（如 GitHub 加速代理），排在最前。"""
    mirrors = [("github", github_url(name)), ("gitee", gitee_url(name))]
    env = os.environ.get("JOBRADAR_MIRROR", "").strip()
    prefer = prefer or (env if env in ("github", "gitee") else None)
    if prefer == "gitee":
        mirrors.reverse()
    if env.startswith("http"):
        mirrors.insert(0, ("mirror", f"{env.rstrip('/')}/{github_url(name)}"))
    return mirrors


def open_db(kind: str, required: bool = True):
    path = home() / DB_FILES[kind]
    if not path.exists():
        if required:
            raise NoData(f"本地没有数据：{path}。先运行 `jobradar update`。")
        return None
    return connect(path, kind)


@contextmanager
def db(kind: str, required: bool = True):
    """打开本地库，退出时关闭。

    Windows 上未关闭的连接会一直锁着文件：`jobradar update` 的最后一步是
    `tmp.replace(dest)`，库文件被锁时会报 PermissionError: [WinError 32]。
    MCP server 常驻进程，不关闭还会每调用一次泄漏一个句柄。
    """
    conn = open_db(kind, required)
    if conn is None:
        yield None
        return
    try:
        yield conn
    finally:
        conn.close()


def envelope(conn, results, *, as_of: str | None = None, **extra) -> dict:
    """统一的返回包装。conn 为 jobs.db；日历等其他库传 conn=None 并显式给出 as_of。"""
    as_of = as_of if conn is None else q.data_as_of(conn)
    stale = as_of is None or (parse_ts(now_ts()) - parse_ts(as_of)).total_seconds() > STALE_HOURS * 3600
    return {"data_as_of": as_of, "stale": stale, **extra, "results": results}
