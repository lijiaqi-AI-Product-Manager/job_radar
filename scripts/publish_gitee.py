"""暂存完整数据代，匿名校验后切换稳定别名；失败不先删除上一代。"""

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx

from jobradar.snapshot_manifest import digest_file, verify_manifest

API = "https://gitee.com/api/v5/repos/{repo}"
TAG = "data-latest"
CHUNK_MB = float(os.environ.get("GITEE_CHUNK_MB", "4"))
MAX_PARTS = 99


def verify_generation(client, repo, tag, manifest):
    """匿名并行落盘分片，顺序重读并验证整文件；不复用其他标签的缓存。"""
    if not re.fullmatch(r"data-(?:[a-f0-9]{20}|latest)", tag):
        raise ValueError("非法数据代标签")
    with tempfile.TemporaryDirectory(prefix="gitee-verify-") as directory:
        cache, pending = {}, []
        for name, info in manifest.get("files", {}).items():
            if not re.fullmatch(r"(?:jobs\.db\.gz|jd_text\.db\.gz|calendar\.db\.gz|crawl-summary\.json)", name):
                raise ValueError("非法快照文件名")
            for index, part in enumerate(info["parts"], 1):
                expected = name if len(info["parts"]) == 1 else f"{name}.part{index:02d}"
                if part["name"] != expected or type(part["size"]) is not int or part["size"] < 0:
                    raise ValueError("非法分片")
                url = f"https://gitee.com/{repo}/releases/download/{tag}/{expected}"
                path = Path(directory) / str(len(pending))
                cache[url] = path
                pending.append((url, path, part))

        def download(item):
            url, path, part = item
            digest, size = hashlib.sha256(), 0
            with client.stream("GET", url, follow_redirects=True) as response, path.open("wb") as handle:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > part["size"]:
                        raise ValueError("匿名分片超过声明大小")
                    digest.update(chunk)
                    handle.write(chunk)
            if size != part["size"] or digest.hexdigest() != part["sha256"]:
                raise ValueError(f"{part['name']} 匿名下载摘要不匹配")
            print(f"gitee: anonymously verified {part['name']}", flush=True)

        with ThreadPoolExecutor(max_workers=16) as pool:
            for future in [pool.submit(download, item) for item in pending]:
                future.result()

        def chunks(path):
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    yield chunk

        class Downloaded:
            @contextmanager
            def stream(self, method, url, **kwargs):
                yield SimpleNamespace(raise_for_status=lambda: None, iter_bytes=lambda: chunks(cache[url]))

        verify_manifest(Downloaded(), repo, tag, manifest)


def split_file(path, chunk_bytes, out_dir):
    parts = []
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            if len(parts) >= MAX_PARTS:
                raise ValueError("分片超过99片")
            part = out_dir / f"{path.name}.part{len(parts) + 1:02d}"
            part.write_bytes(chunk)
            parts.append(part)
    return parts


def _release(client, base, token, tag):
    response = client.get(f"{base}/releases/tags/{tag}", params={"access_token": token})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def ensure_release(client, base, token, tag):
    existing = _release(client, base, token, tag)
    if existing:
        return existing
    response = client.get(base, params={"access_token": token})
    response.raise_for_status()
    branch = response.json().get("default_branch") or "master"
    response = client.post(f"{base}/releases", data={"access_token": token,
        "tag_name": tag, "target_commitish": branch, "name": "Snapshot staging",
        "body": "完整数据代上传中；snapshot-manifest.json 上传并校验前不可作为最新数据。"})
    response.raise_for_status()
    return response.json()


def publish(files, *, token, repo, client, anonymous_client=None):
    base = API.format(repo=repo)
    fingerprint = hashlib.sha256(json.dumps(
        [(p.name, digest_file(p)) for p in sorted(files)], separators=(",", ":")).encode()).hexdigest()[:20]
    tag = "data-" + fingerprint
    owned = anonymous_client is None
    anonymous = anonymous_client or httpx.Client(timeout=httpx.Timeout(180, connect=20), follow_redirects=True)
    try:
        stable = _release(client, base, token, TAG)
        if stable and stable.get("body") == tag:
            response = anonymous.get(f"https://gitee.com/{repo}/releases/download/{TAG}/snapshot-manifest.json")
            response.raise_for_status()
            verify_generation(anonymous, repo, TAG, response.json())
            return
        stage = ensure_release(client, base, token, tag)
        rid = stage["id"]
        existing = {a["name"] for a in stage.get("assets", [])}
        with tempfile.TemporaryDirectory(prefix="gitee-parts-") as directory:
            workdir = Path(directory)
            uploads, manifest = [], {"version": 1, "generation": tag, "files": {}}
            for path in files:
                parts = (split_file(path, int(CHUNK_MB * 1024 * 1024), workdir)
                         if path.stat().st_size > CHUNK_MB * 1024 * 1024 else [path])
                manifest["files"][path.name] = {"sha256": digest_file(path), "size": path.stat().st_size,
                    "parts": [{"name": part.name, "sha256": digest_file(part), "size": part.stat().st_size} for part in parts]}
                uploads.extend(parts)

            def upload(path):
                if path.name in existing:
                    return  # 完整匿名校验还在后面；错误/残缺的旧附件不会被跳过验收。
                for attempt in range(3):
                    try:
                        with path.open("rb") as handle:
                            response = client.post(f"{base}/releases/{rid}/attach_files", data={"access_token": token},
                                                   files={"file": (path.name, handle)})
                        response.raise_for_status()
                        print(f"gitee: uploaded {path.name}", flush=True)
                        return
                    except (httpx.TransportError, httpx.HTTPStatusError):
                        if attempt == 2:
                            raise
                        # 超时可能发生在服务端已接收后；先查询附件，重跑可复用已成功分片。
                        state = _release(client, base, token, tag)
                        if state and any(a["name"] == path.name for a in state.get("assets", [])):
                            return
                        time.sleep(2 ** attempt)

            workers = int(os.environ.get("GITEE_UPLOAD_WORKERS", "4"))
            if not 1 <= workers <= 16:
                raise ValueError("GITEE_UPLOAD_WORKERS 必须在1到16之间")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for future in [pool.submit(upload, path) for path in uploads]:
                    future.result()
            verify_generation(anonymous, repo, tag, manifest)
            marker = workdir / "snapshot-manifest.json"
            marker.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            upload(marker)
            response = anonymous.get(f"https://gitee.com/{repo}/releases/download/{tag}/{marker.name}")
            response.raise_for_status()
            if response.json() != manifest:
                raise ValueError("完成清单与匿名下载不一致")

        def rename(release, new_tag, name, body):
            response = client.patch(f"{base}/releases/{release['id']}", data={"access_token": token,
                "tag_name": new_tag, "name": name, "body": body})
            response.raise_for_status()

        # 旧Release仅改为备份标签，保留所有附件；新代已完整验证才切换。
        try:
            if stable and stable["id"] != rid:
                rename(stable, f"data-previous-{stable['id']}", "Previous data", stable.get("body") or "Previous snapshot")
            rename(stage, TAG, "Latest verified data", tag)
        except BaseException:
            if stable and stable["id"] != rid:
                rename(stable, TAG, stable.get("name") or "Latest data", stable.get("body") or "Previous snapshot")
            raise
        verify_generation(anonymous, repo, TAG, manifest)
        print(f"gitee: verified and promoted {tag}", flush=True)
    finally:
        if owned:
            anonymous.close()


def main():
    token, repo = os.environ.get("GITEE_TOKEN"), os.environ.get("GITEE_REPO")
    if not token or not repo:
        print("GITEE_TOKEN / GITEE_REPO 未配置，跳过国内镜像")
        return 0
    with httpx.Client(timeout=httpx.Timeout(600, connect=30)) as client:
        publish([Path(p) for p in sys.argv[1:]], token=token, repo=repo, client=client)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (httpx.HTTPError, ValueError) as exc:
        # Gitee令牌仅在请求参数中使用，不把含令牌的异常URL写入日志。
        print(f"镜像发布未完成（{type(exc).__name__}），保留上一代与暂存分片", file=sys.stderr)
        sys.exit(1)
