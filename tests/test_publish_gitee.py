import hashlib
import importlib.util
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

spec = importlib.util.spec_from_file_location("publish_gitee", Path(__file__).parent.parent / "scripts/publish_gitee.py")
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)


class Gitee:
    def __init__(self, fail=False, barrier=None):
        self.releases = {9: {"id": 9, "tag_name": "data-latest", "name": "old", "body": "old", "assets": []}}
        self.files, self.calls = {}, []
        self.fail, self.barrier = fail, barrier

    def __call__(self, req):
        path = req.url.path
        self.calls.append((req.method, path))
        if req.method == "DELETE":
            raise AssertionError("不能先删除上一代Release")
        if "/releases/download/" in path:
            tag, name = path.split("/releases/download/")[1].split("/", 1)
            rid = next((rid for rid, r in self.releases.items() if r["tag_name"] == tag), None)
            value = self.files.get((rid, name))
            return httpx.Response(200, content=value) if value is not None else httpx.Response(404)
        if req.method == "GET" and "/releases/tags/" in path:
            tag = path.split("/releases/tags/")[1]
            found = next((r for r in self.releases.values() if r["tag_name"] == tag), None)
            return httpx.Response(200, json=found) if found else httpx.Response(404)
        if req.method == "GET" and re.search(r"/releases/\d+$", path):
            return httpx.Response(200, json=self.releases[int(path.rsplit("/", 1)[1])])
        if req.method == "GET" and path.endswith("/repos/o/r"):
            return httpx.Response(200, json={"default_branch": "main"})
        if req.method == "POST" and path.endswith("/releases"):
            data = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            rid = max(self.releases) + 1
            self.releases[rid] = {"id": rid, "assets": [], **data}
            return httpx.Response(201, json=self.releases[rid])
        if req.method == "POST" and path.endswith("/attach_files"):
            rid = int(path.split("/releases/")[1].split("/")[0])
            name = re.search(rb'filename="([^"]+)"', req.content).group(1).decode()
            if self.fail and name != "snapshot-manifest.json":
                raise httpx.WriteTimeout("simulated", request=req)
            if self.barrier and name != "snapshot-manifest.json":
                self.barrier.wait(timeout=5)
            content = req.content.split(b'filename="' + name.encode() + b'"', 1)[1].split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            self.files[rid, name] = content
            self.releases[rid]["assets"].append({"name": name, "size": len(content)})
            return httpx.Response(201, json={"id": 1})
        if req.method == "PATCH" and "/releases/" in path:
            rid = int(path.rsplit("/", 1)[1])
            data = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            self.releases[rid].update(data)
            return httpx.Response(200, json=self.releases[rid])
        raise AssertionError(f"unexpected {req.method} {path}")


def files(tmp_path):
    result = []
    for name in ("jobs.db.gz", "jd_text.db.gz"):
        path = tmp_path / name
        path.write_bytes(b"verified " + name.encode())
        result.append(path)
    return result


def test_stage_verify_then_promote_without_deleting_old_release(tmp_path):
    state = Gitee()
    with httpx.Client(transport=httpx.MockTransport(state)) as client:
        pg.publish(files(tmp_path), token="fake", repo="o/r", client=client, anonymous_client=client)
    stable = next(r for r in state.releases.values() if r["tag_name"] == "data-latest")
    assert stable["id"] != 9 and state.releases[9]["tag_name"] != "data-latest"
    assert (stable["id"], "snapshot-manifest.json") in state.files
    first_patch = next(i for i, (method, _) in enumerate(state.calls) if method == "PATCH")
    assert any("/releases/download/" in path for _, path in state.calls[:first_patch])


def test_failed_upload_preserves_old_alias_and_never_publishes_ready_marker(tmp_path):
    state = Gitee(fail=True)
    with httpx.Client(transport=httpx.MockTransport(state)) as client, pytest.raises(httpx.HTTPError):
        pg.publish(files(tmp_path), token="fake", repo="o/r", client=client, anonymous_client=client)
    assert state.releases[9]["tag_name"] == "data-latest"
    assert not any(name == "snapshot-manifest.json" for _, name in state.files)
    assert not any(method == "PATCH" for method, _ in state.calls)


def test_uploads_generation_files_in_parallel(tmp_path):
    state = Gitee(barrier=threading.Barrier(2))
    with httpx.Client(transport=httpx.MockTransport(state)) as client:
        pg.publish(files(tmp_path), token="fake", repo="o/r", client=client, anonymous_client=client)


def test_configured_parallel_parts_are_all_verified(tmp_path, monkeypatch):
    monkeypatch.setenv('GITEE_UPLOAD_WORKERS', '16')
    monkeypatch.setattr(pg, 'CHUNK_MB', 8 / 1024 / 1024)
    paths = files(tmp_path)
    for path in paths:
        path.write_bytes(b'01234567' * 8)
    state = Gitee(barrier=threading.Barrier(16))
    with httpx.Client(transport=httpx.MockTransport(state)) as client:
        pg.publish(paths, token="fake", repo="o/r", client=client, anonymous_client=client)
    stable = next(r for r in state.releases.values() if r['tag_name'] == 'data-latest')
    assert sum(rid == stable['id'] and '.part' in name for rid, name in state.files) == 16


def test_skips_without_credentials(monkeypatch, capsys):
    monkeypatch.delenv("GITEE_TOKEN", raising=False)
    monkeypatch.delenv("GITEE_REPO", raising=False)
    assert pg.main() == 0 and "跳过" in capsys.readouterr().out


@pytest.mark.parametrize("path,method,phase,status", [
    ("/api/v5/repos/o/r/releases/10/attach_files", "POST", "分片上传", 403),
    ("/api/v5/repos/o/r/releases/tags/data-latest", "GET", "发布状态读取", 503),
    ("/o/r/releases/download/data-latest/jobs.db.gz", "GET", "匿名下载", 429),
])
def test_failure_diagnostic_exposes_status_and_phase_without_credentials(path, method, phase, status):
    private = "private-session-material"
    request = httpx.Request(method, "https://gitee.com" + path + "?access_token=" + private,
                            headers={"Authorization": "Bearer " + private})
    error = httpx.HTTPStatusError(private, request=request,
                                 response=httpx.Response(status, text=private))
    summary = pg.failure_summary(error)
    assert str(status) in summary and phase in summary
    assert private not in summary and "access_token" not in summary and "https://" not in summary


def test_promotion_failure_restores_previous_stable_alias(tmp_path):
    state = Gitee()

    def transport(req):
        if req.method == "PATCH" and req.url.path.endswith("/releases/10"):
            return httpx.Response(503)
        return state(req)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client, pytest.raises(httpx.HTTPError):
        pg.publish(files(tmp_path), token="fake", repo="o/r", client=client, anonymous_client=client)
    assert state.releases[9]["tag_name"] == "data-latest"
    assert (10, "snapshot-manifest.json") in state.files


def test_same_size_corruption_cannot_promote_generation(tmp_path):
    state = Gitee()

    def transport(req):
        response = state(req)
        if "/releases/download/data-" in req.url.path and not req.url.path.endswith("snapshot-manifest.json"):
            return httpx.Response(200, content=b"x" * len(response.content))
        return response

    with httpx.Client(transport=httpx.MockTransport(transport)) as client, pytest.raises(ValueError):
        pg.publish(files(tmp_path), token="fake", repo="o/r", client=client, anonymous_client=client)
    assert state.releases[9]["tag_name"] == "data-latest"
    assert not any(method == "PATCH" for method, _ in state.calls)


def test_rerun_reuses_verified_files_without_reupload(tmp_path):
    state = Gitee()
    paths = files(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(state)) as client:
        pg.publish(paths, token="fake", repo="o/r", client=client, anonymous_client=client)
        before = sum(method == "POST" for method, _ in state.calls)
        pg.publish(paths, token="fake", repo="o/r", client=client, anonymous_client=client)
    assert sum(method == "POST" for method, _ in state.calls) == before


def test_anonymous_part_verification_is_parallel_and_checks_whole_digest():
    values = [bytes([i]) * 8 for i in range(16)]
    barrier = threading.Barrier(16)
    parts = [{'name':f'jobs.db.gz.part{i+1:02d}','size':len(value),'sha256':hashlib.sha256(value).hexdigest()} for i,value in enumerate(values)]
    manifest = {'version':1,'files':{'jobs.db.gz':{'parts':parts,'size':128,'sha256':hashlib.sha256(b''.join(values)).hexdigest()}}}

    def handler(req):
        assert 'Authorization' not in req.headers
        barrier.wait(timeout=5)
        return httpx.Response(200,content=values[int(req.url.path[-2:])-1])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        pg.verify_generation(client,'o/r','data-'+'a'*20,manifest)


def test_valid_part_hashes_with_wrong_whole_hash_still_fail():
    manifest = {'version':1,'files':{'jobs.db.gz':{'parts':[{'name':'jobs.db.gz','size':3,'sha256':hashlib.sha256(b'abc').hexdigest()}],'size':3,'sha256':'0'*64}}}
    with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'abc'))) as client, pytest.raises(ValueError,match='拼接摘要'):
        pg.verify_generation(client,'o/r','data-'+'a'*20,manifest)


def test_truncated_anonymous_stream_retries_from_empty_file(monkeypatch):
    monkeypatch.setattr(pg.time,'sleep',lambda _:None)
    attempts=[]

    class Truncated(httpx.SyncByteStream):
        def __iter__(self):
            yield b'ab'
            raise httpx.RemoteProtocolError('truncated transport')

    def handler(req):
        attempts.append(req.url.path)
        return httpx.Response(200,stream=Truncated()) if len(attempts)==1 else httpx.Response(200,content=b'abc')

    digest=hashlib.sha256(b'abc').hexdigest()
    manifest={'version':1,'files':{'jobs.db.gz':{'parts':[{'name':'jobs.db.gz','size':3,'sha256':digest}],'size':3,'sha256':digest}}}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        pg.verify_generation(client,'o/r','data-'+'a'*20,manifest)
    assert len(attempts)==2
