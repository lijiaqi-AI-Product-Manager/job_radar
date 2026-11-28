import base64
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from jobradar.local import snapshot_digests

spec = importlib.util.spec_from_file_location("publish_snapshots", Path(__file__).parents[1] / "scripts/publish_snapshots.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

spec = importlib.util.spec_from_file_location("download_snapshots", Path(__file__).parents[1] / "scripts/download_snapshots.py")
downloader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloader)


def test_first_crawl_requires_absence_of_both_local_and_published_history(tmp_path, monkeypatch):
    recorded = tmp_path / "release-snapshot.json"
    recorded.write_text("{}")
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: pytest.fail("known history"))
    assert not downloader.first_publication(recorded)
    recorded.unlink()
    for tags, expected in [("data-archive\n", False), ("data-latest\n", False), ("", True)]:
        monkeypatch.setattr(subprocess, "check_output", lambda *a, value=tags, **kw: value)
        assert downloader.first_publication(recorded) is expected

    def offline(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(subprocess, "check_output", offline)
    with pytest.raises(subprocess.CalledProcessError):
        downloader.first_publication(recorded)


def test_publication_requires_the_three_restored_database_digests(tmp_path):
    for name in publisher.FILES:
        (tmp_path / name).write_bytes(name.encode())
    manifest = publisher.make_manifest(tmp_path)
    marker = base64.b64encode(json.dumps(manifest).encode()).decode()
    current = {"body": "<!--jobradar-snapshot:" + marker + "-->", "assets": []}
    restored = dict(snapshot_digests(current))
    publisher.check_restored_base(current, restored)
    for name in publisher.FILES:
        other = {**restored, name: "sha256:" + "0" * 64}
        with pytest.raises(ValueError):
            publisher.check_restored_base(current, other)
        with pytest.raises(ValueError):
            publisher.check_restored_base(current, {k: v for k, v in restored.items() if k != name})
    for bad in (None, [], {}, {name: "" for name in publisher.FILES}):
        with pytest.raises(ValueError):
            publisher.check_restored_base(current, bad)


def test_first_publication_rejects_existing_legacy_databases_but_allows_staging():
    publisher.check_restored_base({"assets": [{"name": "new-content-jobs.db.gz"}]}, {})
    for name in publisher.ALIASES:
        with pytest.raises(ValueError):
            publisher.check_restored_base({"assets": [{"name": name, "digest": ""}]}, {})


@pytest.mark.parametrize("concurrent_publication", [False, True])
def test_publish_rechecks_base_before_switching_manifest(tmp_path, monkeypatch, concurrent_publication):
    def release(content):
        return {"assets": [
            {"name": name, "digest": "sha256:" + content * 64} for name in publisher.FILES
        ]}

    previous = release("a")
    restored = tmp_path / "download-manifest.json"
    restored.write_text(json.dumps(dict(snapshot_digests(previous))), encoding="utf-8")
    for name in publisher.FILES:
        (tmp_path / name).write_bytes(name.encode())
    manifest = publisher.make_manifest(tmp_path)
    next_release = release("b") if concurrent_publication else release("a")
    next_release["assets"].extend({
        "name": item["asset"], "digest": "sha256:" + item["sha256"], "size": item["size"],
    } for item in manifest["files"].values())
    snapshots = iter([previous, next_release])
    commands = []

    def gh(*args, **kwargs):
        if args[0] == "api":
            return next(snapshots)
        commands.append(args[1])

    monkeypatch.setattr(publisher, "gh", gh)
    monkeypatch.setattr(publisher, "finish_publication", lambda *args: commands.append("aliases") or [])
    if concurrent_publication:
        with pytest.raises(ValueError, match="在恢复后已换代"):
            publisher.publish_generation(tmp_path, manifest, restored)
        assert commands == ["upload"]
    else:
        publisher.publish_generation(tmp_path, manifest, restored)
        assert commands == ["upload", "edit", "aliases"]


def test_manifest_is_content_addressed_and_stable(tmp_path):
    for name in publisher.FILES:
        (tmp_path / name).write_bytes(name.encode())
    a = publisher.make_manifest(tmp_path)
    assert a == publisher.make_manifest(tmp_path)
    (tmp_path / publisher.FILES[0]).write_bytes(b"a different immutable snapshot")
    b = publisher.make_manifest(tmp_path)
    assert a["generation"] != b["generation"]
    assert a["files"]["jd_text.db.gz"] == b["files"]["jd_text.db.gz"]
    assert set(a["files"]) == {"jobs.db.gz", "jd_text.db.gz", "calendar.db.gz"}


def test_no_committed_manifest_uses_legacy_metadata():
    assert snapshot_digests({"body": "legacy", "assets": [{"name": "jobs.db.gz", "digest": "sha256:test"}]}) == {"jobs.db.gz": "sha256:test"}


def _alias(tmp_path, name="jd_text.db"):
    path = tmp_path / name
    path.write_bytes(b"verified compatibility snapshot")
    return path, {"name": name, "digest": "sha256:" + publisher.digest_file(path), "size": path.stat().st_size}


def test_unchanged_alias_does_not_get_deleted_and_uploaded(tmp_path, monkeypatch):
    _, asset = _alias(tmp_path)
    calls = []

    def gh(*args, **kwargs):
        calls.append(args)
        assert args[0] == "api"
        return {"assets": [asset]}

    monkeypatch.setattr(publisher, "gh", gh)
    publisher.publish_aliases(tmp_path, (asset["name"],))
    assert len(calls) == 1


def test_alias_upload_retries_404_without_replacing_completed_aliases(tmp_path, monkeypatch):
    ready_path, ready = _alias(tmp_path, "jobs.db.gz")
    path, asset = _alias(tmp_path)
    assets = [ready]
    uploads = []
    delays = []

    def gh(*args, **kwargs):
        if args[0] == "api":
            return {"assets": assets.copy()}
        assert args[:3] == ("release", "upload", "data-latest")
        assert str(ready_path) not in args
        assert args[3] == str(path)
        uploads.append(args)
        if len(uploads) == 1:
            raise subprocess.CalledProcessError(1, args, stderr="HTTP 404")
        assets.append(asset)

    monkeypatch.setattr(publisher, "gh", gh)
    monkeypatch.setattr(publisher, "sleep", delays.append, raising=False)
    publisher.publish_aliases(tmp_path, (ready["name"], asset["name"]))
    assert len(uploads) == 2
    assert len(delays) == 1


def test_lost_upload_response_is_verified_before_retry(tmp_path, monkeypatch):
    _, asset = _alias(tmp_path)
    assets = []
    uploads = []

    def gh(*args, **kwargs):
        if args[0] == "api":
            return {"assets": assets.copy()}
        uploads.append(args)
        assets.append(asset)
        raise subprocess.CalledProcessError(1, args, stderr="connection lost after upload")

    monkeypatch.setattr(publisher, "gh", gh)
    monkeypatch.setattr(publisher, "sleep", lambda _: None, raising=False)
    publisher.publish_aliases(tmp_path, (asset["name"],))
    assert len(uploads) == 1


def test_alias_upload_failure_remains_a_failure_after_bounded_retries(tmp_path, monkeypatch):
    _, asset = _alias(tmp_path)
    uploads = []

    def gh(*args, **kwargs):
        if args[0] == "api":
            return {"assets": []}
        uploads.append(args)
        raise subprocess.CalledProcessError(1, args, stderr="HTTP 404")

    monkeypatch.setattr(publisher, "gh", gh)
    monkeypatch.setattr(publisher, "sleep", lambda _: None, raising=False)
    with pytest.raises(RuntimeError, match="jd_text.db"):
        publisher.publish_aliases(tmp_path, (asset["name"],))
    assert len(uploads) == 3


@pytest.mark.parametrize("field, value", [("digest", "sha256:wrong"), ("size", 1)])
def test_alias_requires_both_digest_and_size(tmp_path, monkeypatch, field, value):
    _, asset = _alias(tmp_path)
    assets = [{**asset, field: value}]
    uploads = []

    def gh(*args, **kwargs):
        if args[0] == "api":
            return {"assets": assets.copy()}
        uploads.append(args)
        assets[:] = [asset]

    monkeypatch.setattr(publisher, "gh", gh)
    monkeypatch.setattr(publisher, "sleep", lambda _: None, raising=False)
    publisher.publish_aliases(tmp_path, (asset["name"],))
    assert len(uploads) == 1


def test_wrong_remote_digest_never_counts_as_published(tmp_path, monkeypatch):
    _, asset = _alias(tmp_path)
    uploads = []

    def gh(*args, **kwargs):
        if args[0] == "api":
            return {"assets": [{**asset, "digest": "sha256:wrong"}]}
        uploads.append(args)

    monkeypatch.setattr(publisher, "gh", gh)
    monkeypatch.setattr(publisher, "sleep", lambda _: None, raising=False)
    with pytest.raises(RuntimeError, match="jd_text.db"):
        publisher.publish_aliases(tmp_path, (asset["name"],))
    assert len(uploads) == 3


def test_alias_repair_cannot_target_immutable_files(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "gh", lambda *a, **kw: pytest.fail("must not contact release"))
    with pytest.raises(ValueError):
        publisher.publish_aliases(tmp_path, ("12345678901234567890-jd_text.db.gz",))


def test_retention_only_runs_after_all_compatibility_aliases_are_verified(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(publisher, "publish_aliases", lambda home: calls.append("aliases") or list(publisher.ALIASES))
    monkeypatch.setattr(publisher.subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    aliases = publisher.finish_publication(tmp_path, {"id": 123}, tmp_path)
    assert aliases == list(publisher.ALIASES) and calls[0] == "aliases"
    assert "prune_snapshot_assets.py" in calls[1][0][1] and "--record" in calls[1][0]
    assert "--apply" not in calls[1][0]
    assert calls[1][1]["check"] is True


def test_partial_alias_failure_never_starts_retention(tmp_path, monkeypatch):
    def fail(home):
        raise RuntimeError("aliases not verified")
    monkeypatch.setattr(publisher, "publish_aliases", fail)
    monkeypatch.setattr(publisher.subprocess, "run", lambda *a, **kw: pytest.fail("must preserve all remote files"))
    with pytest.raises(RuntimeError, match="aliases"):
        publisher.finish_publication(tmp_path, {"id": 123}, tmp_path)
