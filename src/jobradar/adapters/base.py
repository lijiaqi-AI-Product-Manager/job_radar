"""适配器基类与注册表。

一个适配器 = 一种"取数方式"（某家自研站，或某个招聘平台如 Moka/北森）。
一个 SourceConfig（sources/*.yaml 的一项）= 该适配器的一个实例（一家公司/一个租户）。
新增适配器请复制 example.py，不要从零写。
"""

import importlib
import pkgutil
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import ClassVar

import httpx

from jobradar.models import Job, SourceConfig

USER_AGENT = (
    "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
    "polite crawler; contact via GitHub issues)"
)


class SkipRecord(Exception):
    """normalize() 遇到无法/不该入库的记录（如缺关键字段）时抛出，该条被跳过。"""


class Adapter(ABC):
    id: ClassVar[str]  # 小写蛇形，必须与模块文件名一致，如 "moka"、"tencent"

    def __init__(self, source: SourceConfig, client: httpx.Client, *,
                 sleep: Callable[[float], None] = time.sleep):
        self.source = source
        self.client = client
        self._sleep = sleep
        self._last_request = 0.0

    # ---- 子类只需实现这两个 ----
    @abstractmethod
    def fetch_raw(self) -> Iterator[dict]:
        """翻页拉取该源当前全部在招岗位的原始记录。必须遵守 self.source.max_pages。"""

    @abstractmethod
    def normalize(self, raw: dict) -> Job:
        """原始记录 -> Job。无法处理时抛 SkipRecord。"""

    # ---- 基类提供 ----
    def fetch_all(self) -> Iterator[Job]:
        for raw in self.fetch_raw():
            try:
                yield self.normalize(raw)
            except SkipRecord:
                continue

    def request_json(self, method: str, url: str, *, params=None, json=None) -> dict:
        """限速 + 重试(仅 5xx/429/网络错误) 的 JSON 请求。适配器里一律用它，不要直接用 client。"""
        for attempt in range(3):
            self._throttle()
            try:
                r = self.client.request(method, url, params=params, json=json)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                retryable = isinstance(e, httpx.TransportError) or (
                    e.response.status_code == 429 or e.response.status_code >= 500
                )
                if not retryable or attempt == 2:
                    raise
                self._sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")

    def _throttle(self):
        wait = (1.0 / self.source.rate_limit_rps) - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        transport=transport,
    )


# ---- 注册表 ----
_REGISTRY: dict[str, type[Adapter]] = {}
_NOT_ADAPTERS = {"base", "recording"}


def register(cls: type[Adapter]) -> type[Adapter]:
    if cls.id in _REGISTRY and _REGISTRY[cls.id] is not cls:
        raise ValueError(f"duplicate adapter id: {cls.id}")
    _REGISTRY[cls.id] = cls
    return cls


def load_all(include_drafts: bool = False) -> dict[str, type[Adapter]]:
    """加载全部适配器。以 _ 开头的模块是草稿（还没录 fixtures/写测试），默认不加载，
    只有 scripts/record_fixtures.py 会带 include_drafts=True 加载它们。"""
    import jobradar.adapters as pkg

    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name in _NOT_ADAPTERS or m.name.startswith("__"):
            continue
        if m.name.startswith("_") and not include_drafts:
            continue
        importlib.import_module(f"{pkg.__name__}.{m.name}")
    if include_drafts:
        return dict(_REGISTRY)
    return {k: v for k, v in _REGISTRY.items() if not v.__module__.rsplit(".", 1)[-1].startswith("_")}
