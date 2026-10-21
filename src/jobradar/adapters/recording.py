"""fixtures 的录制与回放。

录制：scripts/record_fixtures.py 用 RecordingTransport 包住真实网络，把每个响应存成文件 + manifest.json。
回放：ReplayTransport 在测试里按 (method, url, body) 精确匹配返回；匹配不到就报错，
      所以测试永远不会碰真实网络，适配器改了请求方式也会立刻被发现。
"""

import json
import re
from pathlib import Path

import httpx

REDACTED = "REDACTED"


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
    """secret_patterns：适配器声明的匿名会话 token 正则（各带一个分组）。响应里匹配到的值记下来，
    写入 fixtures 前在响应体、请求 URL、请求体里一律替换成 REDACTED；适配器拿到的仍是真值。"""

    def __init__(self, directory: Path, inner: httpx.BaseTransport | None = None,
                 secret_patterns: list[str] | None = None):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.inner = inner or httpx.HTTPTransport()
        self.entries: list[dict] = []
        self.patterns = [re.compile(p) for p in secret_patterns or []]
        self.secrets: set[str] = set()

    def _scrub(self, text: str) -> str:
        for s in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(s, REDACTED)
        return text

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        content = response.read()
        ctype = response.headers.get("content-type", "application/json")
        ext = "json" if "json" in ctype else "txt"
        name = f"{len(self.entries) + 1:03d}.{ext}"
        stored = content
        if self.patterns:
            text = content.decode("utf-8", errors="replace")
            for p in self.patterns:
                self.secrets.update(m for m in p.findall(text) if m)
            stored = self._scrub(text).encode("utf-8")
        (self.dir / name).write_bytes(stored)
        self.entries.append({
            "method": request.method, "url": self._scrub(str(request.url)), "body": self._scrub(_body(request)),
            "status": response.status_code, "content_type": ctype, "file": name,
        })
        (self.dir / "manifest.json").write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # 原样把响应头交给客户端（含 Set-Cookie，匿名会话要用），只去掉与已解码正文不符的传输头；
        # 响应头不写入 fixtures，所以 cookie 不会落盘
        headers = [(k, v) for k, v in response.headers.multi_items()
                   if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
        return httpx.Response(response.status_code, headers=headers, content=content, request=request)
