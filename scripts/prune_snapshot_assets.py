"""保留完整清单历史后清理无引用快照附件；默认仅预演，发布锁内才可应用。"""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from jobradar.local import snapshot_digests

REPO = "lijiaqi-AI-Product-Manager/job_radar"
API = f"https://api.github.com/repos/{REPO}"
UPLOADS = f"https://uploads.github.com/repos/{REPO}"
FILES = ("jobs.db.gz", "jd_text.db.gz", "calendar.db.gz")
RECORD = re.compile(r"manifest-([a-f0-9]{20})-([a-f0-9]{20})\.json")
IMMUTABLE = re.compile(r"([a-f0-9]{20})-(?:jobs\.db\.gz|jd_text\.db\.gz|calendar\.db\.gz|jd_text\.compact\.db\.gz|jd_text\.rows\.jsonl\.xz)")
MAX_RECORD_BYTES = 65536


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("asset timestamp must include timezone")
    return stamp


def manifest_bytes(manifest):
    marker = base64.b64encode(json.dumps(manifest).encode()).decode()
    snapshot_digests({"body": f"<!--jobradar-snapshot:{marker}-->"})
    if set(manifest) - {"version", "generation", "files", "variants"}:
        raise ValueError("unknown manifest fields")
    if set(manifest.get("variants", {})) - {"text_compact", "text_stream"}:
        raise ValueError("unknown manifest variant")
    generation = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()[:20]
    if generation != manifest["generation"]:
        raise ValueError("manifest generation does not match files")
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError("manifest too large")
    return payload


def manifest_name(manifest):
    sha = hashlib.sha256(manifest_bytes(manifest)).hexdigest()
    return f"manifest-{manifest['generation']}-{sha[:20]}.json"


def _manifest(release):
    body = release.get("body") or ""
    markers = re.findall(r"<!--jobradar-snapshot:(.*?)-->", body, re.S)
    if len(markers) != 1:
        raise ValueError("exactly one committed snapshot manifest is required")
    manifest = json.loads(base64.b64decode(markers[0], validate=True))
    manifest_bytes(manifest)
    return manifest


def _references(manifest):
    return {item["asset"]: item for item in [*manifest["files"].values(), *manifest.get("variants", {}).values()]}


def _request(client, method, path, **kwargs):
    response = client.request(method, API + path, **kwargs)
    response.raise_for_status()
    return response


def _assets(client, release_id):
    assets = []
    for page in range(1, 21):
        items = _request(client, "GET", f"/releases/{release_id}/assets", params={"per_page": 100, "page": page}).json()
        if not isinstance(items, list):
            raise ValueError("invalid asset page")
        assets.extend(items)
        if len(items) < 100:
            if len({a["id"] for a in assets}) != len(assets) or len({a["name"] for a in assets}) != len(assets):
                raise ValueError("duplicate asset metadata")
            return assets
    raise ValueError("asset pagination limit reached; no cleanup permitted")


def _release(client):
    release = _request(client, "GET", "/releases/tags/data-latest").json()
    if type(release.get("id")) is not int or release.get("tag_name") != "data-latest" or release.get("draft"):
        raise ValueError("unexpected release")
    _manifest(release)
    release["assets"] = _assets(client, release["id"])
    return release


def _verify_references(manifests, assets):
    actual = {a["name"]: a for a in assets}
    for manifest in manifests:
        for name, item in _references(manifest).items():
            found = actual.get(name, {})
            if found.get("digest") != "sha256:" + item["sha256"] or found.get("size") != item["size"]:
                raise ValueError(f"referenced asset missing or changed: {name}")


def _record(client, release, manifest):
    _verify_references([manifest], release["assets"])
    payload, name = manifest_bytes(manifest), manifest_name(manifest)
    expected = "sha256:" + hashlib.sha256(payload).hexdigest()
    existing = next((a for a in release["assets"] if a["name"] == name), None)
    if existing:
        if existing.get("size") != len(payload) or existing.get("digest") != expected:
            raise ValueError("existing manifest record is inconsistent; refusing overwrite")
        return
    response = client.post(UPLOADS + f"/releases/{release['id']}/assets", params={"name": name},
                           content=payload, headers={"Content-Type": "application/json"})
    response.raise_for_status()
    item = response.json()
    if item.get("name") != name or item.get("size") != len(payload) or item.get("digest") != expected:
        raise ValueError("manifest upload not verified")
    release["assets"].append(item)


def _history(client, assets):
    records = []
    for asset in assets:
        match = RECORD.fullmatch(asset["name"])
        if not match:
            continue
        if type(asset.get("size")) is not int or not 0 < asset["size"] <= MAX_RECORD_BYTES:
            raise ValueError("manifest record size invalid")
        response = _request(client, "GET", f"/releases/assets/{asset['id']}",
                            headers={"Accept": "application/octet-stream"}, follow_redirects=True)
        payload = response.content
        sha = hashlib.sha256(payload).hexdigest()
        if (len(payload) != asset["size"] or asset.get("digest") != "sha256:" + sha or sha[:20] != match[2]):
            raise ValueError("manifest record digest mismatch")
        manifest = json.loads(payload)
        if manifest_bytes(manifest) != payload or manifest_name(manifest) != asset["name"]:
            raise ValueError("manifest record name or content invalid")
        records.append((asset, manifest))
    return records


def _ledger(assets):
    return {a["id"]: {key: a.get(key) for key in ("name", "size", "digest", "created_at", "updated_at")} for a in assets}


def maintain(client, *, now=None, apply=False, record=False, previous=None, approved_ids=None):
    if apply and (not isinstance(approved_ids, (set, frozenset, list, tuple))
                  or not 0 < len(approved_ids) <= 100 or any(type(i) is not int or i <= 0 for i in approved_ids)):
        raise ValueError("cleanup requires explicit approved attachment IDs")
    now = now or datetime.now(UTC)
    release = _release(client)
    current = _manifest(release)
    if apply or record:
        if previous is not None:
            if previous.get("id") != release["id"] or previous.get("tag_name") != "data-latest":
                raise ValueError("previous manifest is from a different release")
            _record(client, release, _manifest(previous))
        _record(client, release, current)
        release = _release(client)
        if _manifest(release) != current:
            raise ValueError("publication changed during manifest recording")
    records = _history(client, release["assets"])
    records.sort(key=lambda r: (_stamp(r[0]["created_at"]), r[0]["id"]), reverse=True)
    generations = list(dict.fromkeys(m["generation"] for _, m in records))
    result = {"generation": current["generation"], "asset_count": len(release["assets"]),
              "retained_generations": generations[:3], "candidates": [], "deleted": [], "deferred": None,
              "approved_ids": sorted(set(approved_ids or []))}
    _verify_references([current], release["assets"])
    if len(generations) < 3 or current["generation"] not in generations:
        result["deferred"] = "insufficient_generation_history"
        return result
    keep = set(generations[:3]) | {current["generation"]}
    cutoff = now - timedelta(hours=72)
    protected = [r for r in records if r[1]["generation"] in keep or _stamp(r[0]["updated_at"]) >= cutoff]
    _verify_references([m for _, m in protected], release["assets"])
    names = {a["name"] for a, _ in protected}
    names.update(name for _, m in protected for name in _references(m))
    names.update(_references(current))
    for asset in release["assets"]:
        match = IMMUTABLE.fullmatch(asset["name"])
        record = RECORD.fullmatch(asset["name"])
        digest = asset.get("digest") or ""
        if (asset["name"] in names or (not match and not record)
                or _stamp(asset["updated_at"]) >= cutoff or _stamp(asset["created_at"]) >= cutoff):
            continue
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest) or (match and digest[7:27] != match[1]):
            continue
        result["candidates"].append({key: asset[key] for key in ("id", "name", "size")})
    if not apply:
        return result
    expected = _ledger(release["assets"])
    for asset in result["candidates"]:
        if asset["id"] not in approved_ids:
            continue
        fresh = _release(client)
        if fresh["id"] != release["id"] or fresh["body"] != release["body"] or _ledger(fresh["assets"]) != expected:
            raise ValueError("release or assets changed; stopped cleanup")
        _request(client, "DELETE", f"/releases/assets/{asset['id']}")
        expected.pop(asset["id"])
        result["deleted"].append(asset["id"])
    return result


def asset_ids(text):
    items = [part.strip() for part in text.split(",")]
    if (len(text) > 3000 or not 0 < len(items) <= 100
            or any(not re.fullmatch(r"[1-9][0-9]*", part) for part in items)):
        raise ValueError("asset IDs must be explicit positive integers")
    values = {int(part) for part in items}
    if len(values) != len(items):
        raise ValueError("duplicate asset IDs")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="仅在采集发布互斥锁内执行")
    parser.add_argument("--record", action="store_true", help="只补齐清单记录并生成预演，不删除附件")
    parser.add_argument("--asset-ids", default="", help="预演后明确确认的附件编号，逗号分隔；应用必填")
    parser.add_argument("--previous", type=Path, help="本次发布切换前实际读取的Release元数据")
    args = parser.parse_args()
    try:
        approved = asset_ids(args.asset_ids) if args.apply or args.asset_ids else None
    except ValueError as error:
        parser.error(str(error))
    token = os.environ.get("GH_TOKEN", "").strip()
    if (args.apply or args.record) and not token:
        token = subprocess.run(["gh", "auth", "token"], check=True, capture_output=True,
                               text=True, encoding="utf-8").stdout.strip()
    if (args.apply or args.record) and not token:
        parser.error("记录或应用需要发布环境的GH_TOKEN或已登录的gh")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "jobradar-snapshot-maintenance"}
    if token:
        headers["Authorization"] = "Bearer " + token
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    with httpx.Client(headers=headers, timeout=60) as client:
        print(json.dumps(maintain(client, apply=args.apply, record=args.record,
                                  previous=previous, approved_ids=approved), ensure_ascii=False))


if __name__ == "__main__":
    main()
