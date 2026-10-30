import httpx
import pytest

from jobradar.adapters.base import USER_AGENT, make_client
from jobradar.compliance import ComplianceError, RobotsPolicy


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def read(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


def policy(clock=None):
    clock = clock or Clock()
    return RobotsPolicy(clock=clock.read, sleep=clock.sleep)


def test_disallowed_path_is_never_requested():
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /private/")

    with make_client(transport=httpx.MockTransport(handle), policy=policy()) as client:
        with pytest.raises(ComplianceError, match="Disallow"):
            client.get("https://example.com/private/jobs")
    assert seen == ["https://example.com/robots.txt"]


def test_redirect_destination_is_checked_before_following_it():
    seen = []

    def handle(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            rule = "/" if request.url.host == "blocked.example" else ""
            return httpx.Response(200, text=f"User-agent: *\nDisallow: {rule}")
        return httpx.Response(302, headers={"location": "https://blocked.example/private/jobs"})

    with make_client(transport=httpx.MockTransport(handle), policy=policy()) as client:
        with pytest.raises(ComplianceError):
            client.get("https://allowed.example/jobs")
    assert seen == ["https://allowed.example/robots.txt", "https://allowed.example/jobs",
                    "https://blocked.example/robots.txt"]


def test_cache_and_rate_limit_apply_to_the_origin_with_fixed_ua():
    clock = Clock()
    seen = []

    def handle(request):
        assert request.headers["user-agent"] == USER_AGENT
        seen.append((request.url.path, clock.now))
        return httpx.Response(200, text="User-agent: *\nCrawl-delay: 2" if request.url.path == "/robots.txt" else "jobs")

    with make_client(transport=httpx.MockTransport(handle), policy=policy(clock)) as client:
        client.get("https://example.com/jobs")
        client.get("https://example.com/detail")
    assert seen == [("/robots.txt", 0), ("/jobs", 2), ("/detail", 4)]


def test_failed_robots_check_does_not_request_content():
    seen = []

    def handle(request):
        seen.append(request.url.path)
        return httpx.Response(503)

    with make_client(transport=httpx.MockTransport(handle), policy=policy()) as client:
        with pytest.raises(ComplianceError, match="无法核实"):
            client.get("https://example.com/jobs")
    assert seen == ["/robots.txt"]


def test_http_200_challenge_is_not_accepted_as_job_content():
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text='<html><meta name="aliyun_waf_aa" content="challenge"></html>')

    with make_client(transport=httpx.MockTransport(handle), policy=policy()) as client:
        with pytest.raises(ComplianceError, match="挑战"):
            client.get("https://example.com/jobs")


def test_known_terms_restriction_stops_before_any_network_request():
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(404)

    with make_client(transport=httpx.MockTransport(handle), policy=policy()) as client:
        with pytest.raises(ComplianceError, match="书面许可"):
            client.get("https://m.yingjiesheng.com/other/index.html")
    assert seen == []


def test_modified_client_agent_stops_before_any_network_request():
    seen = []
    with make_client(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(404)),
                     policy=policy()) as client:
        client.headers["User-Agent"] = "different-agent"
        with pytest.raises(ComplianceError, match="UA"):
            client.get("https://example.com/jobs")
    assert seen == []


def test_robots_redirect_cannot_visit_a_known_terms_restricted_domain():
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://www.yingjiesheng.com/robots.txt"})

    with make_client(transport=httpx.MockTransport(handle), policy=policy()) as client:
        with pytest.raises(ComplianceError):
            client.get("https://example.com/jobs")
    assert seen == ["https://example.com/robots.txt"]
