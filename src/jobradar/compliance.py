"""实际请求前复核 robots；按主机缓存并限速，重定向目标也必须通过检查。"""

import re
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from jobradar.http_limits import DEADLINE_EXTENSION, RequestBudgetExceeded, check_deadline
from jobradar.robots import _decision, fetch_robots

PROBE_EXTENSION = "jobradar_robots_probe"


def terms_block_reason(host: str) -> str | None:
    host = host.rstrip(".").lower()
    if host == "yingjiesheng.com" or host.endswith(".yingjiesheng.com"):
        return ("应届生用户协议第五节要求抓取/转载前取得书面许可，当前未提供此许可；"
                "https://www.yingjiesheng.com/about/service/user-agreement202108.pdf")
    return None


class ComplianceError(RuntimeError):
    """访问许可不明确或明确禁止；不得由网络重试逻辑绕过。"""


def _crawl_delay(lines: list[str]) -> float:
    agents = []
    rules_started = False
    delay = 1.0
    for raw in lines:
        key, _, value = raw.split("#", 1)[0].strip().partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if rules_started:
                agents = []
                rules_started = False
            agents.append(value.lower())
        elif key:
            rules_started = True
            if key == "crawl-delay" and any(a in ("*", "jobradar") for a in agents):
                try:
                    candidate = float(value)
                except ValueError:
                    continue
                if candidate >= 0:
                    delay = max(delay, candidate)
    return delay


class RobotsPolicy:
    def __init__(self, *, ttl_seconds: float = 21600,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, min_interval: float = 1):
        self.ttl = ttl_seconds
        self.min_interval = max(1, min_interval)
        self.clock, self.sleep = clock, sleep
        self._cache: dict[str, tuple[float, str, list[str]]] = {}
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._lock = threading.Lock()

    def _pace(self, origin: str, interval: float, deadline=None) -> None:
        check_deadline(deadline)
        previous = self._last.get(origin)
        wait = interval - (self.clock() - previous) if previous is not None else 0
        if wait > 30:
            raise ComplianceError("站点要求的请求间隔超出本次等待预算，暂停该源")
        if wait > 0:
            if deadline is not None:
                wait = min(wait, max(0, deadline-time.monotonic()))
            self.sleep(wait)
            check_deadline(deadline)
        self._last[origin] = self.clock()

    def on_request(self, client: httpx.Client, request: httpx.Request) -> None:
        from jobradar.adapters.base import USER_AGENT

        deadline = request.extensions.get(DEADLINE_EXTENSION)
        check_deadline(deadline)
        if request.headers.get("user-agent") != USER_AGENT:
            raise ComplianceError("请求 UA 必须使用项目固定 USER_AGENT，不能按站点替换")
        parts = urlsplit(str(request.url))
        reason = terms_block_reason(parts.hostname or "")
        if reason:
            raise ComplianceError(reason)
        if request.extensions.get(PROBE_EXTENSION):
            return
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            lock = self._locks.setdefault(origin, threading.RLock())
        acquired = lock.acquire(timeout=max(0, deadline-time.monotonic())) if deadline is not None else lock.acquire()
        if not acquired:
            raise RequestBudgetExceeded("request budget exceeded waiting for robots check")
        try:
            check_deadline(deadline)
            cached = self._cache.get(origin)
            ttl = min(self.ttl, 30) if cached and cached[1] == "unreachable" else self.ttl
            if cached is None or self.clock() - cached[0] >= ttl:
                self._pace(origin, 1, deadline)
                status, lines = fetch_robots(client, str(request.url), deadline=deadline)
                cached = (self.clock(), status, lines)
                self._cache[origin] = cached
            _, status, lines = cached
            if status == "unreachable":
                raise ComplianceError(f"{origin}: robots.txt 无法核实，暂停访问")
            permitted, rule = _decision(lines, str(request.url))
            if not permitted:
                raise ComplianceError(f"{origin}{parts.path}: robots Disallow: {rule}")
            self._pace(origin, max(self.min_interval, _crawl_delay(lines)), deadline)
            if deadline is not None:
                remaining = max(.001, deadline-time.monotonic())
                timeout = request.extensions.get("timeout", {})
                request.extensions["timeout"] = {k:min(v,remaining) if v is not None else remaining for k,v in timeout.items()}
        finally:
            lock.release()

    @staticmethod
    def on_response(response: httpx.Response) -> None:
        if response.request.extensions.get(PROBE_EXTENSION):
            return
        response.read()
        text = response.content[:8192].decode("utf-8", errors="replace")
        if re.search(r'<meta[^>]+name=["\']aliyun_waf_aa["\']', text, re.I):
            raise ComplianceError("公开入口返回 WAF 挑战页，停止该源，不执行或生成挑战凭据")
