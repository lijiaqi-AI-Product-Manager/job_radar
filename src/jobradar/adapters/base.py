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
    # 站点下发给匿名访客的 token 的正则（各带一个分组）。录制 fixtures 时据此脱敏（docs/DEVELOPMENT.md 铁律 1）
    secret_patterns: ClassVar[list[str]] = []

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

    def request_json(self, method: str, url: str, *, params=None, data=None, json=None,
                     headers=None) -> dict:
        """限速 + 重试(仅 5xx/429/网络错误) 的 JSON 请求。适配器里一律用它，不要直接用 client。
        headers 只用于浏览器本来就会带的 Referer/Origin 等；User-Agent 固定，传了也会被忽略。
        data 用于 `application/x-www-form-urlencoded` 的 POST（Tupu360 的 nextPageList 就是这样）。"""
        r = self._request(method, url, params=params, data=data, json=json, headers=headers)
        try:
            return r.json()
        except ValueError as e:  # json.JSONDecodeError 是 ValueError 的子类
            # 2026-10-24 实测：Workday 被限流时返回 303/500 + 空 body，原来只报
            # "Expecting value: line 1 column 1" —— 排障时完全看不出是被挡了。
            ct = (r.headers.get("content-type") or "")[:40]
            body = " ".join(r.text[:120].split())
            raise RuntimeError(
                f"{method} {url.split('?')[0]} 返回的不是 JSON（HTTP {r.status_code}, {ct}）：{body!r}。"
                "常见原因：被限流/反爬拦截（Workday 会给 303/500），或接口已改版。"
            ) from e

    def request_text(self, method: str, url: str, *, params=None, data=None, json=None,
                     headers=None) -> str:
        """同 request_json，返回文本（用于服务端渲染的 HTML 页面）。"""
        return self._request(method, url, params=params, data=data, json=json, headers=headers).text

    def _request(self, method: str, url: str, *, params=None, data=None, json=None,
                 headers=None) -> httpx.Response:
        headers = {k: v for k, v in (headers or {}).items() if k.lower() != "user-agent"} or None
        for attempt in range(3):
            self._throttle()
            try:
                r = self.client.request(method, url, params=params, data=data, json=json,
                                        headers=headers)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                return r
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


def make_client(transport: httpx.BaseTransport | None = None, *, policy=None) -> httpx.Client:
    # 显式 transport 是 fixtures/测试注入点；真实网络默认开启 robots 守卫。
    if policy is None and transport is None:
        from jobradar.compliance import RobotsPolicy

        policy = RobotsPolicy()
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        transport=transport,
    )
    if policy is not None:
        client.event_hooks["request"].append(lambda request: policy.on_request(client, request))
        client.event_hooks["response"].append(policy.on_response)
    return client


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
