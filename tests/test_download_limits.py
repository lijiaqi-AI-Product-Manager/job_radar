import gzip
import hashlib
import threading

import httpx
import pytest

from jobradar import cli
from jobradar.store.migrate import connect


def sample(tmp_path):
    path = tmp_path / "sample.db"
    connect(path, "jobs", defer_search_index=True).close()
    body = path.read_bytes()
    blob = gzip.compress(body, mtime=0)
    halves = [blob[: len(blob) // 2], blob[len(blob) // 2 :]]
    parts = [
        {"name": f"jobs.db.gz.part{i}", "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
        for i, b in zip(("01", "02"), halves, strict=True)
    ]
    info = {"size": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "parts": parts}
    return (
        body,
        halves,
        {"version": 1, "generation": "data-" + "a" * 20, "files": {"jobs.db.gz": info}},
    )


@pytest.fixture(autouse=True)
def anonymous(monkeypatch):
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "JOBRADAR_MIRROR"):
        monkeypatch.delenv(key, raising=False)


def test_manifest_parts_are_parallel_verified_and_not_guessed(tmp_path):
    body, halves, manifest = sample(tmp_path)
    barrier = threading.Barrier(2, timeout=2)
    seen = []

    def handler(req):
        name = req.url.path.rsplit("/", 1)[-1]
        seen.append(name)
        if name == "snapshot-manifest.json":
            return httpx.Response(200, json=manifest)
        if name in {"jobs.db.gz.part01", "jobs.db.gz.part02"}:
            barrier.wait()
            return httpx.Response(200, content=halves[int(name[-2:]) - 1])
        return httpx.Response(404)

    digests = {"jobs.db.gz": "sha256:" + manifest["files"]["jobs.db.gz"]["sha256"]}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert (
            cli._download(
                "jobs.db", tmp_path / "jobs.db", client=client, prefer="gitee", digests=digests
            )
            == "gitee"
        )
    assert (tmp_path / "jobs.db").read_bytes() == body
    assert set(seen) == {"snapshot-manifest.json", "jobs.db.gz.part01", "jobs.db.gz.part02"}


def test_corrupt_part_retries_before_falling_back(tmp_path):
    body, halves, manifest = sample(tmp_path)
    seen = []

    def handler(req):
        name = req.url.path.rsplit("/", 1)[-1]
        seen.append(name)
        if name == "snapshot-manifest.json":
            return httpx.Response(200, json=manifest)
        if name.endswith("part01") and seen.count(name) == 1:
            return httpx.Response(200, content=b"truncated")
        if name.endswith(("part01", "part02")):
            return httpx.Response(200, content=halves[int(name[-2:]) - 1])
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cli._download(
            "jobs.db",
            tmp_path / "jobs.db",
            client=client,
            prefer="gitee",
            digests={"jobs.db.gz": "sha256:" + manifest["files"]["jobs.db.gz"]["sha256"]},
        )
    assert seen.count("jobs.db.gz.part01") == 2
    assert (tmp_path / "jobs.db").read_bytes() == body


@pytest.mark.parametrize("fault", ["digest", "path", "size", "order", "empty"])
def test_invalid_mirror_manifest_never_changes_existing_snapshot(tmp_path, fault):
    body, _, manifest = sample(tmp_path)
    dest = tmp_path / "jobs.db"
    dest.write_bytes(body)
    expected = "sha256:" + manifest["files"]["jobs.db.gz"]["sha256"]
    info = manifest["files"]["jobs.db.gz"]
    if fault == "digest":
        info["sha256"] = "0" * 64
    elif fault == "path":
        info["parts"][0]["name"] = "../secret"
    elif fault == "size":
        info["size"] = -1
    elif fault == "order":
        info["parts"].reverse()
    else:
        info["parts"] = []
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return (
            httpx.Response(200, json=manifest)
            if req.url.path.endswith("snapshot-manifest.json")
            else httpx.Response(404)
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(SystemExit):
        cli._download(
            "jobs.db", dest, client=client, prefer="gitee", digests={"jobs.db.gz": expected}
        )
    assert dest.read_bytes() == body
    assert not any("gitee.com" in u and "part01" in u for u in seen)
    assert not list(tmp_path.glob("*.part"))


def test_metadata_size_is_bounded_before_json_parse(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 17))
    ) as client:
        with pytest.raises(ValueError, match="上限"):
            cli._fetch(client, "https://example.test/manifest", {}, tmp_path, max_bytes=16)
    assert list(tmp_path.iterdir()) == []


def test_part_budget_is_shared_instead_of_restarting_per_request(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cli, "_now", lambda: clock[0])

    class Drip(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] += 3
            yield b"data"

    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Drip()))
    ) as client:
        with pytest.raises(httpx.ReadTimeout):
            cli._fetch(client, "https://example.test/part", {}, tmp_path, deadline=2)
    assert list(tmp_path.iterdir()) == []
