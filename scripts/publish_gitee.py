"""把数据文件同步到 Gitee 发行版（国内下载镜像）。由 mirror.yml 在 daily-crawl 发布 GitHub Release 之后调用。

用法：python scripts/publish_gitee.py <file> [<file> ...]
环境变量：GITEE_TOKEN（Gitee 私人令牌，需 projects 权限）、GITEE_REPO（owner/repo）

为什么每次重建 release：
2026-10-22 实测发现，Gitee 的「删除单个附件」对大文件不生效（jobs.db.gz 12.5MB 删了仍存在），
同名的旧附件与新附件并存，而 downloads/download/data-latest/<name> 会解析到旧的那份——
镜像工作流显示成功、用户下载到的却是上一天的数据。改成先删整个 release、
再新建并上传，恒为一份；mirror.yml 之后还会用匿名下载校验大小，防止再出现这种"假成功"。
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
    """返回可用的 release id：已存在则整个删掉重建，保证同名附件只有一份。"""
    r = client.get(f"{base}/releases/tags/{TAG}", params={"access_token": token})
    if r.status_code == 200 and r.json():
        stale = r.json()["id"]
        d = client.delete(f"{base}/releases/{stale}", params={"access_token": token})
        if d.status_code not in (200, 204):
            d.raise_for_status()
        print(f"gitee: deleted stale release {TAG} id={stale}（Gitee 删单个大附件不生效）", flush=True)
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

    def upload(f: Path) -> None:
        t0 = time.monotonic()
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
