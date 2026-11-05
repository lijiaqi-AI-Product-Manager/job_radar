import base64
import hashlib
import importlib.util
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location("snapshot_retention", Path(__file__).parents[1] / "scripts/prune_snapshot_assets.py")
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)

NOW = datetime(2026, 11, 5, 8, tzinfo=UTC)


class Release:
    def __init__(self):
        self.assets = []
        self.bodies = {}
        self.deleted = []
        self.uploaded = []
        self.pages = []
        self.release = {"id": 12, "tag_name": "data-latest", "draft": False, "body": ""}
        self.current = None
        self.on_delete_check = None

    def asset(self, name, body, *, days=5):
        stamp = (NOW - timedelta(days=days)).isoformat()
        item = {"id": 100 + len(self.bodies), "name": name, "size": len(body),
                "digest": "sha256:" + hashlib.sha256(body).hexdigest(), "created_at": stamp, "updated_at": stamp}
        self.bodies[item["id"]] = body
        self.assets.append(item)
        return item

    def generation(self, label, *, days=5, record=True, shared=None):
        files = {}
        for name in retention.FILES:
            body = (label + name).encode()
            sha = hashlib.sha256(body).hexdigest()
            item = self.asset(sha[:20] + "-" + name, body, days=days)
            files[name] = {"sha256": sha, "size": len(body), "asset": item["name"]}
        if shared:
            files["jd_text.db.gz"] = deepcopy(shared["files"]["jd_text.db.gz"])
        generation = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:20]
        manifest = {"version": 1, "generation": generation, "files": files}
        if record:
            payload = retention.manifest_bytes(manifest)
            self.asset(retention.manifest_name(manifest), payload, days=days)
        self.current = manifest
        marker = base64.b64encode(json.dumps(manifest).encode()).decode()
        self.release["body"] = f"<!--jobradar-snapshot:{marker}-->"
        return manifest

    def request(self, req):
        path = req.url.path
        if req.method == "GET" and path.endswith("/releases/tags/data-latest"):
            if self.on_delete_check and self.deleted:
                self.on_delete_check(self)
            return httpx.Response(200, json=self.release)
        if req.method == "GET" and path.endswith("/releases/12/assets"):
            page, size = int(req.url.params["page"]), int(req.url.params["per_page"])
            self.pages.append(page)
            return httpx.Response(200, json=self.assets[(page - 1) * size:page * size])
        if req.method == "GET" and "/releases/assets/" in path:
            return httpx.Response(200, content=self.bodies[int(path.rsplit("/", 1)[1])])
        if req.method == "POST" and path.endswith("/releases/12/assets"):
            item = self.asset(req.url.params["name"], req.content, days=0)
            self.uploaded.append(item["name"])
            return httpx.Response(201, json=item)
        if req.method == "DELETE" and "/releases/assets/" in path:
            item_id = int(path.rsplit("/", 1)[1])
            self.assets = [a for a in self.assets if a["id"] != item_id]
            self.deleted.append(item_id)
            return httpx.Response(204)
        pytest.fail(f"unexpected request: {req.method} {req.url}")

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.request))


def history():
    release = Release()
    old = release.generation("old", days=8)
    release.generation("previous-two", days=7, shared=old)
    release.generation("previous", days=6)
    release.generation("current", days=5)
    return release, old


def test_dry_run_keeps_three_generations_and_old_files_reused_by_them():
    release, old = history()
    with release.client() as client:
        result = retention.maintain(client, now=NOW)
    names = {a["name"] for a in result["candidates"]}
    assert old["files"]["jobs.db.gz"]["asset"] in names
    assert old["files"]["jd_text.db.gz"]["asset"] not in names
    assert len(result["retained_generations"]) == 3
    assert not release.deleted and not release.uploaded


def test_safety_window_uses_manifest_references_and_asset_update_time():
    release, old = history()
    old_record = next(a for a in release.assets if a["name"] == retention.manifest_name(old))
    old_record["updated_at"] = (NOW - timedelta(hours=71)).isoformat()
    with release.client() as client:
        names = {a["name"] for a in retention.maintain(client, now=NOW)["candidates"]}
    assert not names & {v["asset"] for v in old["files"].values()}
    assert old_record["name"] not in names


def test_aliases_diagnostics_unknown_names_and_new_assets_are_never_deleted():
    release, _ = history()
    names = ["jobs.db", "jd_text.db", "calendar.db", *retention.FILES, "crawl-summary.json",
             "detail-progress-unrelated.json.gz", "not-a-digest-jobs.db.gz"]
    for name in names:
        release.asset(name, b"keep", days=10)
    recent = release.asset("e" * 20 + "-jobs.db.gz", b"new", days=0)
    with release.client() as client:
        result = retention.maintain(client, now=NOW, apply=True)
    remaining = {a["name"] for a in release.assets}
    assert set(names) <= remaining and recent["name"] in remaining
    assert result["deleted"] and release.deleted


@pytest.mark.parametrize("count", [0, 1, 2])
def test_incomplete_generation_history_never_permits_deletion(count):
    release = Release()
    for number in range(count):
        release.generation(str(number), days=5)
    if count == 0:
        release.generation("unrecorded", record=False)
    with release.client() as client:
        result = retention.maintain(client, now=NOW)
    assert result["deferred"] == "insufficient_generation_history" and not result["candidates"]


def test_paginated_assets_are_all_seen():
    release, old = history()
    old_asset = next(a for a in release.assets if a["name"] == old["files"]["jobs.db.gz"]["asset"])
    for i in range(110):
        release.asset(f"unrelated-{i}", b"keep")
    release.assets.remove(old_asset)
    release.assets.append(old_asset)
    with release.client() as client:
        result = retention.maintain(client, now=NOW)
    assert old_asset["id"] in {a["id"] for a in result["candidates"]} and 2 in release.pages


def test_missing_protected_file_aborts_before_any_deletion():
    release, _ = history()
    name = release.current["files"]["jobs.db.gz"]["asset"]
    release.assets = [a for a in release.assets if a["name"] != name]
    with release.client() as client, pytest.raises(ValueError, match="referenced"):
        retention.maintain(client, now=NOW, apply=True)
    assert not release.deleted


@pytest.mark.parametrize("corruption", ["payload", "name", "digest"])
def test_invalid_history_cannot_be_used_as_a_cleanup_authorization(corruption):
    release, old = history()
    item = next(a for a in release.assets if a["name"] == retention.manifest_name(old))
    if corruption == "payload":
        release.bodies[item["id"]] = b"{}"
    elif corruption == "name":
        item["name"] = item["name"].replace(old["generation"], "f" * 20)
    else:
        item["digest"] = "sha256:" + "0" * 64
    with release.client() as client, pytest.raises(ValueError):
        retention.maintain(client, now=NOW, apply=True)
    assert not release.deleted


def test_concurrent_manifest_change_stops_remaining_deletions():
    release, _ = history()
    release.on_delete_check = lambda state: state.release.update(body=state.release["body"] + "changed")
    with release.client() as client, pytest.raises(ValueError, match="changed"):
        retention.maintain(client, now=NOW, apply=True)
    assert len(release.deleted) == 1


def test_current_and_verified_previous_manifests_are_recorded_without_overwrite():
    release = Release()
    previous = deepcopy(release.release)
    release.generation("previous", record=False)
    previous.update(deepcopy(release.release))
    release.generation("current", record=False)
    with release.client() as client:
        result = retention.maintain(client, now=NOW, apply=True, previous=previous)
        retention.maintain(client, now=NOW, apply=True, previous=previous)
    assert len(release.uploaded) == 2 and not release.deleted
    assert result["deferred"] == "insufficient_generation_history"


def test_unexpected_variant_is_not_silently_ignored():
    release, _ = history()
    manifest = deepcopy(release.current)
    manifest["variants"] = {"future_format": {"asset": "something"}}
    with pytest.raises(ValueError):
        retention.manifest_bytes(manifest)


def test_all_supported_text_variants_are_protected_by_current_manifest():
    release, _ = history()
    manifest = deepcopy(release.current)
    manifest["variants"] = {}
    for key, name in [("text_compact", "jd_text.compact.db.gz"), ("text_stream", "jd_text.rows.jsonl.xz")]:
        body = name.encode()
        sha = hashlib.sha256(body).hexdigest()
        item = release.asset(sha[:20] + "-" + name, body, days=10)
        manifest["variants"][key] = {"version": 1, "sha256": sha, "size": len(body), "asset": item["name"],
                                      "source_sha256": manifest["files"]["jd_text.db.gz"]["sha256"]}
    marker = base64.b64encode(json.dumps(manifest).encode()).decode()
    release.release["body"] = f"<!--jobradar-snapshot:{marker}-->"
    with release.client() as client:
        retention.maintain(client, now=NOW, apply=True)
    assert {i["asset"] for i in manifest["variants"].values()} <= {a["name"] for a in release.assets}


def test_rerun_after_cleanup_is_safe_and_requires_no_further_deletions():
    release, _ = history()
    with release.client() as client:
        first = retention.maintain(client, now=NOW, apply=True)
        second = retention.maintain(client, now=NOW, apply=True)
    assert first["deleted"] and not second["deleted"]


def test_asset_arriving_before_first_delete_aborts_cleanup():
    release, _ = history()
    original = release.request
    checked = 0

    def respond(req):
        nonlocal checked
        if req.url.path.endswith("/releases/tags/data-latest"):
            checked += 1
            if checked == 3:
                release.asset("new-publication", b"new", days=0)
        return original(req)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(ValueError, match="changed"):
        retention.maintain(client, now=NOW, apply=True)
    assert not release.deleted


def test_recording_history_only_does_not_apply_the_cleanup_plan():
    release, _ = history()
    release.generation("new-unrecorded", record=False)
    with release.client() as client:
        result = retention.maintain(client, now=NOW, record=True)
    assert release.uploaded and result["candidates"]
    assert not result["deleted"] and not release.deleted
