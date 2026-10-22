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
    a = _A(src, make_client(httpx.MockTransport(handler)), sleep=lambda s: None)
    a.request_json("GET", "https://x.invalid/", headers={"Referer": "https://x.invalid/p", "User-Agent": "Mozilla/5.0"})
    assert seen["referer"] == "https://x.invalid/p"
    assert seen["user-agent"] == USER_AGENT
