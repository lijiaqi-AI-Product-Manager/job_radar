import importlib.util
from pathlib import Path

import httpx

spec = importlib.util.spec_from_file_location(
    "publish_gitee", Path(__file__).parent.parent / "scripts" / "publish_gitee.py")
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)

BASE = "https://gitee.com/api/v5/repos/o/r"


def test_creates_release_and_replaces_same_name_asset(tmp_path):
    f = tmp_path / "jobs.db.gz"
    f.write_bytes(b"x" * 10)
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        path = req.url.path
        if path.endswith("/releases/tags/data-latest"):
            return httpx.Response(404, json={"message": "Not Found"})
        if req.method == "GET" and path == "/api/v5/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if req.method == "POST" and path.endswith("/releases"):
            assert b"target_commitish=main" in req.content
            return httpx.Response(201, json={"id": 9})
        if req.method == "GET" and path.endswith("/releases/9/attach_files"):
            return httpx.Response(200, json=[{"name": "jobs.db.gz", "id": 3}, {"name": "other", "id": 4}])
        if req.method == "DELETE":
            return httpx.Response(204)
        if req.method == "POST" and path.endswith("/releases/9/attach_files"):
            assert b'filename="jobs.db.gz"' in req.content
            return httpx.Response(201, json={"id": 5})
        raise AssertionError(f"unexpected {req.method} {path}")

    pg.publish([f], token="t", repo="o/r", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert ("DELETE", "/api/v5/repos/o/r/releases/9/attach_files/3") in calls
    assert ("DELETE", "/api/v5/repos/o/r/releases/9/attach_files/4") not in calls
    assert calls[-1] == ("POST", "/api/v5/repos/o/r/releases/9/attach_files")


def test_skips_without_credentials(monkeypatch, capsys):
    monkeypatch.delenv("GITEE_TOKEN", raising=False)
    monkeypatch.delenv("GITEE_REPO", raising=False)
    assert pg.main() == 0 and "跳过" in capsys.readouterr().out
