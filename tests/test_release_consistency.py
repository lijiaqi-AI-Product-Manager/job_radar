import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest


def test_preflight_supports_non_utf8_windows_console():
    script = Path(__file__).parents[1] / "scripts/check_release_consistency.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        env=dict(os.environ, PYTHONIOENCODING="cp1252"),
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("ascii", "replace")


def module():
    path = Path(__file__).parents[1] / "scripts/check_release_consistency.py"
    spec = importlib.util.spec_from_file_location("consistency", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "before,after,old,new,allowed",
    [
        ("same", "same", "1.2.3", "1.2.3", True),
        ("old", "new", "1.2.3", "1.2.3", False),
        ("old", "new", "1.2.3", "1.2.4", True),
        ("old", "new", "1.2.3", "1.2.2", False),
    ],
)
def test_readme_only_pr_cannot_leave_pypi_behind(before, after, old, new, allowed):
    if allowed:
        module().validate_readme_change(before, after, old, new)
    else:
        with pytest.raises(ValueError):
            module().validate_readme_change(before, after, old, new)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/install-target.json").write_text(
        json.dumps({"version": "1.2.3", "revision": "v1.2.3"})
    )
    snapshot = {
        "generation": "a" * 20,
        "data_as_of": "2026-11-05T08:58:42Z",
        "total_jobs": 1000,
        "visible_jobs": 900,
        "calendar_entries": 20,
        "calendar_manual": 10,
    }
    (tmp_path / "docs/release-snapshot.json").write_text(json.dumps(snapshot))
    body = "招聘快照 · 2026-11-05T08:58:42Z\n1,000 / 900 / 20 / 10\n"
    for name in ("README.md", "README.en.md"):
        (tmp_path / name).write_text(body, encoding="utf-8")
    (tmp_path / "docs/COVERAGE.md").write_text(body, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("## 1.2.3 — 2026-11-05\n内容\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "file,replacement",
    [
        ("README.en.md", "wrong counts"),
        ("README.md", "wrong date"),
        ("docs/COVERAGE.md", "wrong coverage"),
        ("CHANGELOG.md", "## 1.2.2\nold"),
        ("docs/install-target.json", '{"version":"1.2.2","revision":"v1.2.2"}'),
    ],
)
def test_inconsistent_sources_block_release(root, file, replacement):
    (root / file).write_text(replacement, encoding="utf-8")
    with pytest.raises(ValueError):
        module().validate(root, "1.2.3")


def test_matching_sources_pass_without_network(root):
    assert module().validate(root, "1.2.3")["total_jobs"] == 1000


def test_public_metadata_must_match_main_readme_and_snapshot(root):
    mod = module()
    snapshot = mod.validate(root, "1.2.3")
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    ) as client:
        with pytest.raises(ValueError):
            mod.verify_online(root, snapshot, client)


@pytest.mark.parametrize("drift", [None, "main", "generation", "counts"])
def test_online_gate_detects_changes_before_upload(root, drift):
    mod = module()
    snapshot = mod.validate(root, "1.2.3")
    body = (root / "README.md").read_bytes()
    manifest = {"generation": snapshot["generation"] if drift != "generation" else "b" * 20}
    proof = {
        "snapshot_generation": snapshot["generation"],
        "data_as_of": snapshot["data_as_of"],
        "statistics": dict(snapshot),
    }
    if drift == "counts":
        proof["statistics"]["total_jobs"] = 1234

    def respond(request):
        if "/contents/" in request.url.path:
            value = {
                "encoding": "base64",
                "content": base64.b64encode(b"changed" if drift == "main" else body).decode(),
            }
        elif "/releases/tags/" in request.url.path:
            value = {
                "body": "<!--jobradar-snapshot:"
                + base64.b64encode(json.dumps(manifest).encode()).decode()
                + "-->"
            }
        else:
            value = proof
        return httpx.Response(200, json=value)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if drift:
            with pytest.raises(ValueError):
                mod.verify_online(root, snapshot, client)
        else:
            mod.verify_online(root, snapshot, client)


@pytest.mark.parametrize("drift", [None, "wheel", "sdist", "version"])
def test_built_descriptions_must_match_source(root, drift):
    body = (root / "README.md").read_bytes()
    version = "1.2.2" if drift == "version" else "1.2.3"
    with zipfile.ZipFile(root / "jobsearchradar-1.2.3-py3-none-any.whl", "w") as z:
        z.writestr(
            "jobsearchradar-1.2.3.dist-info/METADATA",
            f"Name: jobsearchradar\nVersion: {version}\n\n".encode()
            + (b"old" if drift == "wheel" else body),
        )
    with tarfile.open(root / "jobsearchradar-1.2.3.tar.gz", "w:gz") as t:
        data = b"old" if drift == "sdist" else body
        entry = tarfile.TarInfo("jobsearchradar-1.2.3/README.md")
        entry.size = len(data)
        t.addfile(entry, io.BytesIO(data))
    if drift:
        with pytest.raises(ValueError):
            module().validate_artifacts(root, root, "1.2.3")
    else:
        module().validate_artifacts(root, root, "1.2.3")
