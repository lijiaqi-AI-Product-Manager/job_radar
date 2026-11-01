import importlib.util
from pathlib import Path

from jobradar.local import snapshot_digests

spec = importlib.util.spec_from_file_location("publish_snapshots", Path(__file__).parents[1] / "scripts/publish_snapshots.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


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
