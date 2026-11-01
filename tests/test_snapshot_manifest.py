import base64
import json

import pytest

from jobradar import local


def manifest():
    return {"version": 1, "generation": "a" * 20, "files": {
        name: {"asset": "a" * 20 + "-" + name, "sha256": "a" * 64, "size": 100}
        for name in ("jobs.db.gz", "jd_text.db.gz", "calendar.db.gz")}}


def test_atomic_release_note_routes_only_to_complete_immutable_assets():
    data = manifest()
    body = "Latest data\n<!--jobradar-snapshot:" + base64.b64encode(json.dumps(data).encode()).decode() + "-->"
    digests = local.snapshot_digests({"body": body, "assets": []})
    assert digests["jobs.db.gz"] == "sha256:" + "a" * 64
    assert digests.asset_names["jobs.db.gz"] == "a" * 20 + "-jobs.db.gz"


def test_invalid_committed_manifest_does_not_fall_back_to_mutable_aliases():
    with pytest.raises(ValueError):
        local.snapshot_digests({"body": "<!--jobradar-snapshot:broken-->"})


def test_partial_manifest_is_not_a_publishable_snapshot():
    data = manifest()
    del data["files"]["calendar.db.gz"]
    with pytest.raises(ValueError):
        local.snapshot_digests({"body": "<!--jobradar-snapshot:" + base64.b64encode(json.dumps(data).encode()).decode() + "-->"})
