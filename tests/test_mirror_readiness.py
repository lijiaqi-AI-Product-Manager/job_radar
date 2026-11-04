"""镜像未配置或入口404时不下载大快照；其他故障不能伪装成正常跳过。"""

import importlib.util
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).parents[1]
HTTP_CLIENT = httpx.Client


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("gitee_readiness", ROOT / "scripts/check_gitee_readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("status,payload,ready,state", [
    (404, {}, False, "repository_not_public_or_missing"),
    (200, {"private":True}, False, "repository_private"),
    (200, {"private":False}, True, "public_repository_reachable"),
])
def test_public_probe_never_sends_credentials(checker, status, payload, ready, state):
    requests = []
    def handler(request):
        requests.append(request)
        assert "authorization" not in request.headers and "access_token" not in str(request.url)
        return httpx.Response(status, json=payload)
    with HTTP_CLIENT(transport=httpx.MockTransport(handler)) as client:
        result = checker.probe_public_repository("qgauss/job_radar", client)
    assert result["ready"] is ready and result["state"] == state
    assert len(requests) == 1


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_unexpected_service_errors_remain_failures(checker, status):
    with HTTP_CLIENT(transport=httpx.MockTransport(lambda _:httpx.Response(status))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            checker.probe_public_repository("qgauss/job_radar", client)


@pytest.mark.parametrize("repo", ["../repo", "owner/..", "https://other.test/repo", "a/b\nready=true", "a/b/c"])
def test_invalid_repository_cannot_inject_urls_or_workflow_outputs(checker, repo):
    with HTTP_CLIENT(transport=httpx.MockTransport(lambda _:pytest.fail("invalid repo must not request"))) as client:
        with pytest.raises(ValueError):
            checker.probe_public_repository(repo, client)


def test_missing_credentials_is_explicit_and_does_not_contact_any_service(checker, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GITEE_TOKEN", raising=False)
    monkeypatch.setenv("GITEE_REPO", "qgauss/job_radar")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    monkeypatch.setattr(checker.httpx, "Client", lambda **kw:pytest.fail("missing credentials must not request"))
    assert checker.main() == 0
    output = capsys.readouterr().out
    assert '"ready": false' in output and "credentials_not_configured" in output
    assert "ready=false" in (tmp_path / "output").read_text(encoding="utf-8")
    assert "未执行同步" in (tmp_path / "summary").read_text(encoding="utf-8")


def test_unexpected_error_is_sanitized_and_not_a_green_skip(checker, monkeypatch, capsys):
    monkeypatch.setenv("GITEE_TOKEN", "synthetic-private-value")
    monkeypatch.setenv("GITEE_REPO", "qgauss/job_radar")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    def fail(*args):
        raise httpx.ConnectError("synthetic-private-value should not be echoed")
    monkeypatch.setattr(checker, "probe_public_repository", fail)
    assert checker.main() == 1
    output = capsys.readouterr()
    assert "synthetic-private-value" not in output.out + output.err
    assert "Traceback" not in output.out + output.err
    assert "检测失败" in output.err


def test_download_and_publish_job_depend_on_explicit_readiness():
    workflow = yaml.safe_load((ROOT / ".github/workflows/mirror.yml").read_text(encoding="utf-8"))
    preflight = workflow["jobs"]["preflight"]
    assert preflight["outputs"]["ready"] == "${{ steps.repository.outputs.ready }}"
    assert any("check_gitee_readiness.py" in step.get("run", "") for step in preflight["steps"])
    mirror = workflow["jobs"]["mirror"]
    assert mirror["needs"] == "preflight" and "needs.preflight.outputs.ready == 'true'" in mirror["if"]
    assert not any(step.get("continue-on-error") for step in preflight["steps"] + mirror["steps"])


def test_bad_payload_does_not_claim_readiness(checker):
    with HTTP_CLIENT(transport=httpx.MockTransport(lambda _:httpx.Response(200, json=[]))) as client:
        with pytest.raises(ValueError):
            checker.probe_public_repository("qgauss/job_radar", client)
