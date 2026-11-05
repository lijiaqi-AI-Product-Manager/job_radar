import hashlib
import importlib.util
import subprocess
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location("publish_code_release", ROOT / "scripts/publish_code_release.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def artifacts(tmp_path):
    files = []
    for name in ("jobsearchradar-1.2.3-py3-none-any.whl", "jobsearchradar-1.2.3.tar.gz", "jobradar-skill.zip"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        files.append(path)
    return files


def metadata(files):
    return {"info": {"name": "jobsearchradar", "version": "1.2.3"}, "urls": [
        {"filename": path.name, "size": path.stat().st_size,
         "digests": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}} for path in files[:2]]}


class Releases:
    def __init__(self, existing=None, lost=False):
        self.existing, self.lost, self.calls = existing, lost, []

    def __call__(self, *args, capture=False):
        self.calls.append(args)
        if args[:2] == ("release", "view"):
            if self.existing is None:
                raise subprocess.CalledProcessError(1, args, stderr="release not found")
            return {"apiUrl": "https://api.github.com/repos/lijiaqi-AI-Product-Manager/job_radar/releases/7"}
        if args[0] == "api":
            if self.existing is None:
                raise subprocess.CalledProcessError(1, args, stderr="HTTP 404")
            return self.existing
        if args[:2] == ("release", "create"):
            assert "--draft" in args and "--verify-tag" in args
            self.existing = {"tag_name": "v1.2.3", "draft": True, "assets": []}
        elif args[:2] == ("release", "upload"):
            assert "--clobber" not in args
            path = Path(args[3])
            self.existing["assets"].append({"name": path.name, "size": path.stat().st_size,
                "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()})
            if self.lost:
                self.lost = False
                raise subprocess.CalledProcessError(1, args, stderr="response lost after upload")
        elif args[:2] == ("release", "edit"):
            assert len(self.existing["assets"]) == 3 and "--draft=false" in args
            self.existing["draft"] = False
        else:
            raise AssertionError(args)


def test_release_is_published_only_after_all_files_are_verified(tmp_path):
    mod, files, gh = module(), artifacts(tmp_path), Releases(lost=True)
    mod.publish_github(files, "v1.2.3", "内容", gh=gh, sleep=lambda _: None)
    assert gh.existing["draft"] is False
    assert len([c for c in gh.calls if c[:2] == ("release", "upload")]) == 3
    before = len(gh.calls)
    mod.publish_github(files, "v1.2.3", "新说明不覆盖已发布说明", gh=gh)
    assert all(call[0] == "api" or call[:2] == ("release", "view") for call in gh.calls[before:])


def test_existing_version_asset_is_never_overwritten(tmp_path):
    mod, files = module(), artifacts(tmp_path)
    gh = Releases({"tag_name": "v1.2.3", "draft": False,
                   "assets": [{"name": files[0].name, "size": 1, "digest": "sha256:wrong"}]})
    with pytest.raises(ValueError):
        mod.publish_github(files, "v1.2.3", "内容", gh=gh)
    assert all(call[0] == "api" or call[:2] == ("release", "view") for call in gh.calls)


def test_pypi_digest_mismatch_stops_before_creating_release(tmp_path):
    mod, files = module(), artifacts(tmp_path)
    meta = metadata(files)
    meta["urls"][0]["digests"]["sha256"] = "0" * 64
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=meta)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(ValueError):
        mod.wait_for_pypi(files[:2], "1.2.3", client=client, sleep=lambda _: None)
    assert len(requests) == 1


def test_pypi_propagation_is_bounded_and_requires_both_artifacts(tmp_path):
    mod, files = module(), artifacts(tmp_path)
    count = 0
    def respond(request):
        nonlocal count
        count += 1
        return httpx.Response(404) if count == 1 else httpx.Response(200, json=metadata(files))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        mod.wait_for_pypi(files[:2], "1.2.3", client=client, sleep=lambda _: None)
    assert count == 2
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404))) as client, pytest.raises(ValueError):
        mod.wait_for_pypi(files[:2], "1.2.3", client=client, sleep=lambda _: None, attempts=2)


def test_release_notes_select_exact_version_and_do_not_copy_other_versions():
    mod = module()
    changelog = "# 更新日志\n## 未发布\n草稿\n## 1.2.3 — 2026-11-05\n本版内容\n## 1.2.2 — 2026-11-04\n旧内容\n"
    assert mod.release_notes(changelog, "1.2.3") == "本版内容"
    with pytest.raises(ValueError):
        mod.release_notes(changelog, "1.2.30")


def test_artifact_allowlist_rejects_extra_files_and_mismatched_version(tmp_path):
    mod = module()
    files = artifacts(tmp_path)
    directory = tmp_path / "dist"
    directory.mkdir()
    for file in files[:2]:
        file.rename(directory / file.name)
    assert len(mod.distribution_files(directory, files[2], "1.2.3")) == 3
    with pytest.raises(ValueError):
        mod.distribution_files(directory, files[2], "1.2.4")
    (directory / "jobs.db").write_bytes(b"unexpected data")
    with pytest.raises(ValueError):
        mod.distribution_files(directory, files[2], "1.2.3")


def test_production_tag_preflight_does_not_contact_publication_endpoints(monkeypatch):
    import sys

    mod = module()
    monkeypatch.setattr(mod, "wait_for_pypi", lambda *a, **kw: pytest.fail("preflight must not contact PyPI"))
    monkeypatch.setattr(mod, "publish_github", lambda *a, **kw: pytest.fail("preflight must not write GitHub"))
    monkeypatch.setattr(sys, "argv", ["release", "--check-tag", "--tag", "v" + mod.__version__])
    mod.main()
    monkeypatch.setattr(sys, "argv", ["release", "--check-tag", "--tag", "main"])
    with pytest.raises(SystemExit):
        mod.main()


def test_unpublished_draft_is_resolved_separately_from_published_tag():
    mod = module()
    url = f"https://api.github.com/repos/{mod.REPO}/releases/7"
    draft = {"id": 7, "tag_name": "v1.2.3", "draft": True, "assets": []}
    def read(*args, capture=False):
        if args[:2] == ("release", "view"):
            return {"apiUrl": url}
        if args == ("api", url):
            return draft
        raise subprocess.CalledProcessError(1, args, stderr="HTTP 404")
    assert mod._release("v1.2.3", read) == draft


def test_recovery_artifacts_require_original_tag_commit_and_successful_build():
    mod = module()
    run = {"head_sha": "b" * 40, "path": ".github/workflows/publish.yml", "status": "completed"}
    jobs = [{"name": "build", "conclusion": "success"}, {"name": "publish-pypi", "conclusion": "success"}]
    def read(*args, capture=False):
        path = args[1]
        if "/commits/" in path:
            return {"sha": "a" * 40}
        if path.endswith("/jobs?filter=latest&per_page=100"):
            return {"jobs": jobs}
        return run
    with pytest.raises(ValueError):
        mod.validate_build_run(100, "v1.2.3", gh=read)
    run["head_sha"] = "a" * 40
    assert mod.validate_build_run(100, "v1.2.3", gh=read)["head_sha"] == "a" * 40
    jobs[-1]["conclusion"] = "failure"
    with pytest.raises(ValueError):
        mod.validate_build_run(100, "v1.2.3", gh=read)
