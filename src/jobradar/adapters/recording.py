"""fixtures 的录制与回放。

录制：scripts/record_fixtures.py 用 RecordingTransport 包住真实网络，把每个响应存成文件 + manifest.json。
回放：ReplayTransport 在测试里按 (method, url, body) 精确匹配返回；匹配不到就报错，
      所以测试永远不会碰真实网络，适配器改了请求方式也会立刻被发现。
"""

import json
from pathlib import Path

import httpx


class UnmatchedRequest(AssertionError):
    pass


def _body(request: httpx.Request) -> str:
    return request.content.decode("utf-8") if request.content else ""


class ReplayTransport(httpx.BaseTransport):
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.entries = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = _body(request)
        for e in self.entries:
            if e["method"] == request.method and e["url"] == str(request.url) and e.get("body", "") == body:
                return httpx.Response(
                    e["status"],
                    headers={"content-type": e.get("content_type", "application/json")},
                    content=(self.dir / e["file"]).read_bytes(),
                    request=request,
                )
        raise UnmatchedRequest(f"no fixture for {request.method} {request.url} body={body[:200]!r}")


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, directory: Path, inner: httpx.BaseTransport | None = None):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.inner = inner or httpx.HTTPTransport()
        self.entries: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        content = response.read()
        ctype = response.headers.get("content-type", "application/json")
        ext = "json" if "json" in ctype else "txt"
        name = f"{len(self.entries) + 1:03d}.{ext}"
        (self.dir / name).write_bytes(content)
        self.entries.append({
            "method": request.method, "url": str(request.url), "body": _body(request),
            "status": response.status_code, "content_type": ctype, "file": name,
        })
        (self.dir / "manifest.json").write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return httpx.Response(response.status_code, headers={"content-type": ctype},
                              content=content, request=request)
