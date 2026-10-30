import json

import httpx

from jobradar.adapters.recording import REDACTED, RecordingTransport, ReplayTransport

PAGE = '<script>window.__sysconfig = {__token__: "abc-123-secret"};</script>'
PATTERNS = [r'__token__["\']?\s*:\s*["\']([^"\']+)']


def test_recording_scrubs_session_tokens_and_replay_still_matches(tmp_path):
    # 匿名会话 token 只能在内存里：录制时从响应体、后续请求的 URL/请求体里统一替换成占位符（docs/DEVELOPMENT.md 铁律 1）
    def real(req):
        if req.url.path == "/page":
            return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
        assert req.url.params["_csrf"] == "abc-123-secret"
        return httpx.Response(200, json={"ok": True, "echo": "abc-123-secret"})

    rec = RecordingTransport(tmp_path, inner=httpx.MockTransport(real), secret_patterns=PATTERNS)
    with httpx.Client(transport=rec) as c:
        c.get("https://x.invalid/page")
        c.post("https://x.invalid/api?_csrf=abc-123-secret", json={"t": "abc-123-secret"})

    blob = "".join(p.read_text(encoding="utf-8") for p in tmp_path.iterdir())
    assert "abc-123-secret" not in blob
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest[1]["url"] == f"https://x.invalid/api?_csrf={REDACTED}"

    # 回放：适配器从（已脱敏的）页面取到占位符 token，再用它发请求，正好匹配录制的 URL/请求体
    with httpx.Client(transport=ReplayTransport(tmp_path)) as c:
        assert REDACTED in c.get("https://x.invalid/page").text
        r = c.post(f"https://x.invalid/api?_csrf={REDACTED}", json={"t": REDACTED})
        assert r.json()["ok"] is True


def test_recording_passes_session_cookies_to_client_but_never_stores_them(tmp_path):
    # 录制时客户端要能拿到站点下发的会话 cookie（否则依赖会话的接口 403），但 fixtures 里不能有 cookie
    def real(req):
        if req.url.path == "/page":
            return httpx.Response(200, text="ok", headers={"set-cookie": "SESSION=s3cr3t; Path=/"})
        return httpx.Response(200 if req.headers.get("cookie") == "SESSION=s3cr3t" else 403, json={})

    rec = RecordingTransport(tmp_path, inner=httpx.MockTransport(real))
    with httpx.Client(transport=rec) as c:
        c.get("https://x.invalid/page")
        assert c.post("https://x.invalid/api", json={}).status_code == 200
    blob = "".join(p.read_text(encoding="utf-8") for p in tmp_path.iterdir())
    assert "s3cr3t" not in blob


def test_recording_without_patterns_is_unchanged(tmp_path):
    rec = RecordingTransport(tmp_path, inner=httpx.MockTransport(lambda r: httpx.Response(200, text=PAGE)))
    with httpx.Client(transport=rec) as c:
        c.get("https://x.invalid/page")
    assert "abc-123-secret" in (tmp_path / "001.txt").read_text(encoding="utf-8")


def test_fixture_transform_runs_before_any_body_is_written_and_keeps_live_response(tmp_path):
    original = '<p>private contact</p>'
    recorder = RecordingTransport(tmp_path,
                                  inner=httpx.MockTransport(lambda r: httpx.Response(200, text=original)),
                                  fixture_transform=lambda body, content_type: b'<p>public fixture</p>')
    with httpx.Client(transport=recorder) as client:
        assert client.get('https://example.invalid/jobs').text == original
    assert 'private contact' not in ''.join(p.read_text(encoding='utf-8') for p in tmp_path.iterdir())
    with httpx.Client(transport=ReplayTransport(tmp_path)) as client:
        assert client.get('https://example.invalid/jobs').text == '<p>public fixture</p>'
