"""把数据文件同步到 Gitee 发行版（国内下载镜像）。由 mirror.yml 在 daily-crawl 发布 GitHub Release 之后调用。

用法：python scripts/publish_gitee.py <file> [<file> ...]
环境变量：GITEE_TOKEN（Gitee 私人令牌，需 projects 权限）、GITEE_REPO（owner/repo）、
          GITEE_CHUNK_MB（超过该大小的文件切分片上传，默认 12）

为什么每次重建 release：
2026-10-22 实测发现，Gitee 的「删除单个附件」对大文件不生效（jobs.db.gz 12.5MB 删了仍存在），
同名的旧附件与新附件并存，而 downloads/download/data-latest/<name> 会解析到旧的那份——
镜像工作流显示成功、用户下载到的却是上一天的数据。改成先删整个 release、
再新建并上传，恒为一份；mirror.yml 之后还会用匿名下载校验大小，防止再出现这种"假成功"。

为什么大文件要分片（2026-10-24）：
单连接上行约 11KB/s，jd_text.db.gz（35MB）要传 ~50 分钟以上，实测整轮 mirror 跑了 2 小时、
贴着 workflow 150 分钟超时线。切成 ~12MB 的分片后单个请求更快结束，失败也只需重传那一片。
分片命名 `<name>.part01`、`<name>.part02`…；客户端 `jobradar update` 遇到整文件 404 会自动
按序号下载并拼接（见 cli._fetch_parts），校验仍走 gzip + SQLite quick_check。
"""

import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

API = "https://gitee.com/api/v5/repos/{repo}"
TAG = "data-latest"
CHUNK_MB = float(os.environ.get("GITEE_CHUNK_MB", "12"))
MAX_PARTS = 99


def split_file(f: Path, chunk_bytes: int, out_dir: Path) -> list[Path]:
    """把文件切成 `<name>.partNN`，返回分片路径列表。"""
    parts: list[Path] = []
    with open(f, "rb") as src:
        idx = 1
        while True:
            chunk = src.read(chunk_bytes)
            if not chunk:
                break
            if idx > MAX_PARTS:
                raise RuntimeError(f"{f.name} 太大，{MAX_PARTS} 片放不下")
            p = out_dir / f"{f.name}.part{idx:02d}"
            p.write_bytes(chunk)
            parts.append(p)
            idx += 1
    return parts


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
        "body": ("每日自动更新（GitHub Release data-latest 的国内镜像）。"
                 "jobs.db 为主库，jd_text.db 为 JD 原文库；"
                 f"超过 {CHUNK_MB:.0f}MB 的文件按 .part01/.part02… 分片，"
                 "用 `jobradar update` 会自动下载并合并。"),
    })
    r.raise_for_status()
    return r.json()["id"]


def publish(files: list[Path], *, token: str, repo: str, client: httpx.Client) -> None:
    base = API.format(repo=repo)
    rid = ensure_release(client, base, token)
    print(f"gitee: release {TAG} id={rid}", flush=True)

    workdir = Path(tempfile.mkdtemp(prefix="gitee-parts-"))
    uploads: list[Path] = []
    chunk_bytes = int(CHUNK_MB * 1024 * 1024)
    try:
        for f in files:
            size = f.stat().st_size
            if size <= chunk_bytes:
                uploads.append(f)
                continue
            parts = split_file(f, chunk_bytes, workdir)
            print(f"gitee: {f.name} {size} bytes 超过 {CHUNK_MB:.0f}MB，切成 {len(parts)} 片", flush=True)
            uploads.extend(parts)

        def upload(f: Path) -> None:
            t0 = time.monotonic()
            print(f"gitee: uploading {f.name} ({f.stat().st_size} bytes)…", flush=True)
            with open(f, "rb") as fh:
                r = client.post(f"{base}/releases/{rid}/attach_files", data={"access_token": token},
                                files={"file": (f.name, fh)})
            r.raise_for_status()
            print(f"gitee: uploaded {f.name} ({f.stat().st_size} bytes, {time.monotonic() - t0:.0f}s)",
                  flush=True)

        # 分片并行上传（每个请求更小、更快结束；失败重传代价也小）
        with ThreadPoolExecutor(max_workers=3) as pool:
            for fut in [pool.submit(upload, f) for f in uploads]:
                fut.result()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
