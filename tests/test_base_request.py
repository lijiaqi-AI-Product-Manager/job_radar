import httpx

from jobradar.adapters.base import USER_AGENT, Adapter, make_client
from jobradar.models import SourceConfig


class _A(Adapter):
    id = "probe"

    def fetch_raw(self):
        return iter(())

    def normalize(self, raw):
        raise NotImplementedError


def test_extra_headers_pass_but_user_agent_stays_fixed():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200, json={})

    src = SourceConfig(id="s", company="c", adapter="probe", recruit_types=["campus"], enabled=False)
    a = _A(src, make_client(httpx.MockTransport(handler)), sleep=lambda: None)
    a.request_json("GET", "https://x.invalid/", headers={"Referer": "https://x.invalid/p", "User-Agent": "Mozilla/5.0"})
    assert seen["referer"] == "https://x.invalid/p"
    assert seen["user-agent"] == USER_AGENT


def test_non_json_response_says_what_happened():
    """被限流/拦截时 Workday 会给 303 或 500 + 空 body；报错要能看出是"被挡了"。

    2026-10-24 实测：原来只抛 "Expecting value: line 1 column 1"，排障时完全误导。
    """
    import pytest

    def handler(req):
        # 200 + HTML：不少站点被挡时就是这样（返回登录页/验证页而不是 4xx）
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>blocked</html>")

    src = SourceConfig(id="s", company="c", adapter="probe", recruit_types=["campus"], enabled=False)
    a = _A(src, make_client(httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(RuntimeError) as exc:
        a.request_json("POST", "https://x.invalid/wday/cxs/t/s/jobs")
    msg = str(exc.value)
    assert "不是 JSON" in msg and "200" in msg and "限流" in msg

