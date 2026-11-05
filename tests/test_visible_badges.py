import importlib.util
from pathlib import Path

import httpx
import pytest


def module():
    spec = importlib.util.spec_from_file_location(
        "badges", Path(__file__).parents[1] / "scripts/check_visible_badges.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "origin,cached,repair,success",
    [
        ("2.3.4", "2.3.4", False, True),
        ("2.3.4", "2.3.2", False, False),
        ("2.3.4", "2.3.2", True, True),
        ("2.3.2", "2.3.2", True, False),
    ],
)
def test_checks_actual_github_image_and_only_repairs_when_origin_is_current(
    origin, cached, repair, success
):
    mod = module()
    purged = []

    def respond(r):
        if r.url.host == "github.com":
            return httpx.Response(
                200,
                text='<img src="https://camo.githubusercontent.com/abc/123" data-canonical-src="https://img.shields.io/pypi/v/jobsearchradar?cacheSeconds=300"><img src="https://camo.githubusercontent.com/def/456" data-canonical-src="https://img.shields.io/github/v/release/lijiaqi-AI-Product-Manager/job_radar?cacheSeconds=300">',
            )
        if r.method == "PURGE":
            purged.append(str(r.url))
            return httpx.Response(200, json={"status": "ok"})
        v = origin if r.url.host == "img.shields.io" or str(r.url) in purged else cached
        return httpx.Response(
            200,
            text=f'<svg xmlns="http://www.w3.org/2000/svg" aria-label="PyPI: v{v}"><text>v{v}</text></svg>',
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if success:
            assert len(mod.verify(client, "2.3.4", repair=repair)) == 2
        else:
            with pytest.raises(ValueError):
                mod.verify(client, "2.3.4", repair=repair)
    if origin != "2.3.4":
        assert purged == []


def test_accessible_label_cannot_hide_old_visible_version():
    with pytest.raises(ValueError):
        module().check_svg('<svg aria-label="PyPI: v2.3.4"><text>v2.3.2</text></svg>', "2.3.4")
