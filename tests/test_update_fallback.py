"""公开快照更新不受其他工具令牌影响，授权失败仍保留可用下载路径。"""

import gzip
import hashlib
from contextlib import closing

import httpx
import pytest

from helpers import T, make_job
from jobradar import __version__, cli, local
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect

REAL_REMOTE_DIGESTS = local.remote_digests
HTTP_CLIENT = httpx.Client


@pytest.fixture
def remote(tmp_path, monkeypatch):
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "JOBRADAR_GITHUB_TOKEN", "JOBRADAR_MIRROR"):
        monkeypatch.delenv(name, raising=False)
    directory = tmp_path / "remote"
    directory.mkdir()
    blobs = {}
    for kind, name in local.DB_FILES.items():
        with closing(connect(directory / name, kind, defer_search_index=True)) as conn:
            if kind == "jobs":
                ingest_run(conn, "fixture", [make_job(1, source_id="fixture")], ts=T(1))
        blobs[name + ".gz"] = gzip.compress((directory / name).read_bytes(), mtime=0)
    metadata = {"assets": [{"name": name, "digest": "sha256:" + hashlib.sha256(body).hexdigest()}
                            for name, body in blobs.items()]}
    return blobs, metadata


@pytest.mark.parametrize("variable", ["GITHUB_TOKEN", "GH_TOKEN", "JOBRADAR_GITHUB_TOKEN"])
def test_public_update_ignores_unrelated_or_unused_bad_tokens(tmp_path, monkeypatch, remote, capsys, variable):
    blobs, metadata = remote
    monkeypatch.setenv(variable, "synthetic-expired-token")
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path / "home"))
    seen = []

    def handler(request):
        seen.append(request)
        if request.headers.get("authorization"):
            return httpx.Response(403)
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=metadata)
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=blobs[name]) if name in blobs else httpx.Response(404)

    monkeypatch.setattr(httpx, "Client", lambda **kw: HTTP_CLIENT(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(local, "remote_digests", REAL_REMOTE_DIGESTS)
    cli.main(["update"])
    assert '"updated"' in capsys.readouterr().out
    assert seen and all("authorization" not in request.headers for request in seen)
    assert all(request.headers["user-agent"] == f"jobradar/{__version__}" for request in seen)
    assert all((local.data_dir() / name).is_file() for name in local.DB_FILES.values())


@pytest.mark.parametrize("failure", ["403", "429", "timeout"])
def test_bad_dedicated_token_does_not_prevent_anonymous_raw_fallback(tmp_path, monkeypatch, remote, failure):
    blobs, _ = remote
    monkeypatch.setenv("JOBRADAR_GITHUB_TOKEN", "synthetic-expired-token")
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "api.github.com":
            assert request.headers.get("authorization") == "Bearer synthetic-expired-token"
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic-expired-token must never appear in errors", request=request)
            return httpx.Response(int(failure))
        assert "authorization" not in request.headers
        if str(request.url) == local.github_url("jobs.db"):
            return httpx.Response(200, content=gzip.decompress(blobs["jobs.db.gz"]))
        return httpx.Response(404)

    with HTTP_CLIENT(transport=httpx.MockTransport(handler)) as client:
        assert cli._download("jobs.db", tmp_path / "jobs.db", client=client) == "github"
    assert any(r.url.host == "api.github.com" for r in seen)


@pytest.mark.parametrize("variable", ["GITHUB_TOKEN", "GH_TOKEN", "JOBRADAR_GITHUB_TOKEN"])
def test_all_failed_downloads_have_actionable_errors_and_preserve_data(tmp_path, monkeypatch, remote, variable):
    blobs, _ = remote
    monkeypatch.setenv(variable, "synthetic-private-value")
    dest = tmp_path / "jobs.db"
    before = gzip.decompress(blobs["jobs.db.gz"])
    dest.write_bytes(before)
    with HTTP_CLIENT(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
        with pytest.raises(SystemExit, match="下载") as error:
            cli._download("jobs.db", dest, client=client)
    assert "synthetic-private-value" not in str(error.value)
    assert "Traceback" not in str(error.value)
    assert dest.read_bytes() == before
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("url", ["https://other.invalid/asset", "http://api.github.com/asset",
    f"https://api.github.com/repos/{local.REPO}/releases/assets/7/8",
    f"https://api.github.com/repos/{local.REPO}/releases/assets/7?extra=x",
    "https://api.github.com/repos/another/repository/releases/assets/7"])
def test_auth_asset_metadata_cannot_send_token_outside_the_asset_scope(tmp_path, monkeypatch, remote, url):
    monkeypatch.setenv("JOBRADAR_GITHUB_TOKEN", "synthetic-private-value")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"assets": [{"name": "jobs.db", "url": url}]})

    with HTTP_CLIENT(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            cli._github_api_asset("jobs.db", client, "synthetic-private-value")
    assert all(r.url.host == "api.github.com" for r in seen)


def test_metadata_uses_anonymous_request_before_dedicated_auth(monkeypatch, remote):
    _, metadata = remote
    monkeypatch.setenv("JOBRADAR_GITHUB_TOKEN", "synthetic-purpose-token")
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host != "api.github.com":
            return httpx.Response(404)
        return httpx.Response(200, json=metadata) if request.headers.get("authorization") else httpx.Response(401)

    monkeypatch.setattr(httpx, "Client", lambda **kw: HTTP_CLIENT(transport=httpx.MockTransport(handler), **kw))
    digests = REAL_REMOTE_DIGESTS()
    assert len(digests) == 3
    assert "authorization" not in seen[0].headers
    assert seen[1].headers.get("authorization") == "Bearer synthetic-purpose-token"
