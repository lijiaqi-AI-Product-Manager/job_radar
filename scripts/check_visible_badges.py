"""核对徽章源图与GitHub实际显示的图片，必要时清理单个过期缓存。"""

import argparse
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx

from jobradar import __version__

REPO = "lijiaqi-AI-Product-Manager/job_radar"
PATHS = {"/badge/dynamic/json": "pypi", "/github/v/release/" + REPO: "release"}


class Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        source = a.get("data-canonical-src", "")
        u = urlsplit(source)
        if (
            tag == "img"
            and u.scheme == "https"
            and u.netloc == "img.shields.io"
            and u.path in PATHS
        ):
            if parse_qs(u.query).get("cacheSeconds") != ["300"]:
                raise ValueError("Badge cache policy must be 300 seconds")
            params = parse_qs(u.query)
            if PATHS[u.path] == "pypi" and (
                params.get("url") != ["https://pypi.org/pypi/jobsearchradar/json"]
                or params.get("query") != ["$.info.version"]
            ):
                raise ValueError("PyPI badge must read the official project version")
            self.images[PATHS[u.path]] = (source, a.get("src", ""))


def check_svg(body, version):
    if len(body) > 32768:
        raise ValueError("Badge image exceeds size limit")
    root = ET.fromstring(body)
    label = root.attrib.get("aria-label", "")
    visible = " ".join(
        "".join(n.itertext()) for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "text"
    )
    versions = re.findall(r"v?([0-9]+\.[0-9]+\.[0-9]+)", visible)
    if not label.endswith("v" + version) or not versions or any(v != version for v in versions):
        raise ValueError("Visible badge version does not match release " + version)


def verify(client, version, *, repair=False, purged=None):
    purged = set() if purged is None else purged
    r = client.get("https://github.com/" + REPO)
    r.raise_for_status()
    images = Images()
    images.feed(r.text)
    if set(images.images) != {"pypi", "release"}:
        raise ValueError("GitHub rendered release badges are missing")
    verified = []
    for kind, (origin, cached) in images.images.items():
        u = urlsplit(cached)
        if (
            u.scheme != "https"
            or u.netloc != "camo.githubusercontent.com"
            or u.query
            or not re.fullmatch("/[a-f0-9]+/[a-f0-9]+", u.path)
        ):
            raise ValueError("Unexpected GitHub image proxy URL")
        r = client.get(origin, headers={"Cache-Control": "no-cache"})
        r.raise_for_status()
        check_svg(r.text, version)
        r = client.get(cached, headers={"Cache-Control": "no-cache"})
        r.raise_for_status()
        try:
            check_svg(r.text, version)
        except ValueError:
            if not repair or cached in purged:
                raise
            purged.add(cached)
            result = client.request("PURGE", cached, follow_redirects=False)
            result.raise_for_status()
            if result.json().get("status") != "ok":
                raise ValueError("GitHub image cache refresh failed") from None
            r = client.get(cached, headers={"Cache-Control": "no-cache"})
            r.raise_for_status()
            check_svg(r.text, version)
        verified.append({"badge": kind, "visible_version": version})
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 600:
        parser.error("wait-seconds must be between 0 and 600")
    deadline = time.monotonic() + args.wait_seconds
    purged = set()
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        while True:
            try:
                verified = verify(client, __version__, repair=args.repair, purged=purged)
                print(verified)
                return
            except (ValueError, httpx.HTTPError) as error:
                if time.monotonic() + 10 > deadline:
                    raise SystemExit(str(error)) from None
                print("Waiting for badge image propagation", flush=True)
                time.sleep(10)


if __name__ == "__main__":
    main()
