"""把数据文件同步到 Gitee 发行版（国内下载镜像）。由 mirror.yml 在 daily-crawl 发布 GitHub Release 之后调用。

用法：python scripts/publish_gitee.py <file> [<file> ...]
环境变量：GITEE_TOKEN（Gitee 私人令牌，需 projects 权限）、GITEE_REPO（owner/repo）
发行版标签固定为 data-latest；同名附件先删后传，保证用户拿到的总是最新一份。
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

API = "https://gitee.com/api/v5/repos/{repo}"
TAG = "data-latest"


def ensure_release(client: httpx.Client, base: str, token: str) -> int:
    r = client.get(f"{base}/releases/tags/{TAG}", params={"access_token": token})
    if r.status_code == 200 and r.json():
        return r.json()["id"]
    branch = client.get(base, params={"access_token": token}).json().get("default_branch") or "master"
    r = client.post(f"{base}/releases", data={
        "access_token": token, "tag_name": TAG, "name": "Latest data", "target_commitish": branch,
        "body": "每日自动更新（GitHub Release data-latest 的国内镜像）。jobs.db 为主库，jd_text.db 为 JD 原文库。",
    })
    r.raise_for_status()
    return r.json()["id"]


def publish(files: list[Path], *, token: str, repo: str, client: httpx.Client) -> None:
    base = API.format(repo=repo)
    rid = ensure_release(client, base, token)
    print(f"gitee: release {TAG} id={rid}", flush=True)
    existing = client.get(f"{base}/releases/{rid}/attach_files", params={"access_token": token, "per_page": 100})
    existing.raise_for_status()
    by_name = {a["name"]: a["id"] for a in existing.json()}
    print(f"gitee: existing attachments {sorted(by_name)}", flush=True)

    def upload(f: Path) -> None:
        t0 = time.monotonic()
        if f.name in by_name:
            client.delete(f"{base}/releases/{rid}/attach_files/{by_name[f.name]}",
                          params={"access_token": token}).raise_for_status()
        print(f"gitee: uploading {f.name} ({f.stat().st_size} bytes)…", flush=True)
        with open(f, "rb") as fh:
            r = client.post(f"{base}/releases/{rid}/attach_files", data={"access_token": token},
                            files={"file": (f.name, fh)})
        r.raise_for_status()
        print(f"gitee: uploaded {f.name} ({f.stat().st_size} bytes, {time.monotonic() - t0:.0f}s)", flush=True)

    # 单连接上行很慢（GitHub Actions → Gitee 实测约 11KB/s），各文件并行上传
    with ThreadPoolExecutor(max_workers=max(1, len(files))) as pool:
        for fut in [pool.submit(upload, f) for f in files]:
            fut.result()


def main() -> int:
    token, repo = os.environ.get("GITEE_TOKEN"), os.environ.get("GITEE_REPO")
    if not token or not repo:
        print("GITEE_TOKEN / GITEE_REPO 未配置，跳过国内镜像")
        return 0
    with httpx.Client(timeout=httpx.Timeout(600, connect=30)) as client:
        publish([Path(p) for p in sys.argv[1:]], token=token, repo=repo, client=client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
