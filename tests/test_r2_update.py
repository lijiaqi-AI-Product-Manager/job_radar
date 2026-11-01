import gzip
import hashlib

import httpx
import pytest

from helpers import T, make_job
from jobradar import cli, local
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect


@pytest.mark.parametrize("force", [False, True])
def test_public_update_rejects_old_mirror_and_never_caches_its_new_digest(tmp_path, monkeypatch, force):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    for kind, name in local.DB_FILES.items():
        db = connect(tmp_path / name, kind)
        if kind == "jobs":
            ingest_run(db, "s1", [make_job(1)], ts=T(1))
        db.close()
    original = (tmp_path / "jobs.db").read_bytes()
    fresh = tmp_path / "fresh.db"
    fresh.write_bytes(original)
    with connect(fresh, "jobs") as db:
        db.execute("UPDATE job SET title='新岗位标题'")
    blobs = {name: gzip.compress((fresh if name == "jobs.db" else tmp_path / name).read_bytes(), mtime=0)
             for name in local.DB_FILES.values()}
    digests = {name + ".gz": "sha256:" + hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()}
    monkeypatch.setattr(local, "remote_digests", lambda: digests)
    # 模拟旧版已经错误缓存了新摘要：新版本也不能再相信旧的裸摘要缓存。
    local.save_sync_meta(digests)
    calls = []
    def handler(request):
        calls.append(str(request.url))
        for name in local.DB_FILES.values():
            if str(request.url).endswith("/" + name + ".gz"):
                blob = gzip.compress(original, mtime=0) if name == "jobs.db" else blobs[name]
                return httpx.Response(200, content=blob)
        return httpx.Response(404)
    download = cli._download
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(cli, "_download", lambda name, dest, **kw: download(name, dest, client=client, **kw))
    with pytest.raises(SystemExit):
        cli.main(["update", *( ["--force"] if force else [])])
    assert calls
    assert (tmp_path / "jobs.db").read_bytes() == original
    assert not local.load_sync_meta().get("_verified_assets", {}).get("jobs.db.gz")
    client.close()
