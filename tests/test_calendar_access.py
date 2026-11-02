import httpx
import pytest

from jobradar.core.queries import dead_links
from jobradar.pipeline import calendar as cal
from jobradar.store.migrate import connect


def calendar():
    jobs = connect(":memory:", "jobs")
    conn = connect(":memory:", "calendar")
    row = cal.ManualEntry(
        id="sample",
        group="样本",
        project_type="校招",
        as_of="2026-11-01",
        apply_url="https://entry.test/jobs",
        source={"type": "official_site", "name": "来源", "url": "https://entry.test/jobs"},
    )
    cal.build(
        conn, jobs, manual=[row], sources=[], targets={"sectors": {}}, ts="2026-11-01T00:00:00Z"
    )
    jobs.close()
    return conn


@pytest.mark.parametrize(
    "robots", [httpx.Response(503), httpx.Response(200, text="<html>challenge</html>")]
)
def test_link_probe_never_requests_content_with_unverified_robots(robots):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return robots if req.url.path == "/robots.txt" else httpx.Response(200)

    conn = calendar()
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            cal.check_links(conn, client, ts="2026-11-02T00:00:00Z", sleep=lambda s: None)
        assert seen == ["https://entry.test/robots.txt"]
        assert dead_links(conn, include_errors=True)[0]["status"] == "error"
    finally:
        conn.close()


def test_link_probe_checks_redirect_destination_robots_and_restores_client_hooks():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nDisallow: /" if req.url.host == "blocked.test" else ""
            )
        if req.url.host == "entry.test":
            return httpx.Response(302, headers={"location": "https://blocked.test/private"})
        return httpx.Response(200)

    conn = calendar()
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            hooks = {k: list(v) for k, v in client.event_hooks.items()}
            out = cal.check_links(conn, client, ts="2026-11-02T00:00:00Z", sleep=lambda s: None)
            assert client.event_hooks == hooks
        assert "https://blocked.test/robots.txt" in seen
        assert "https://blocked.test/private" not in seen
        assert out["skipped_robots"] == 1
    finally:
        conn.close()
