"""匿名下载完整代并比对SHA256；仅比较文件大小不足以验收镜像。"""

import os
import sys
from pathlib import Path

import httpx

from jobradar.snapshot_manifest import digest_file, verify_manifest


def main():
    repo = os.environ.get("GITEE_REPO", "qgauss/job_radar")
    paths = [Path(value) for value in sys.argv[1:]]
    if not paths:
        return 2
    with httpx.Client(timeout=httpx.Timeout(180, connect=20), follow_redirects=True) as client:
        response = client.get(f"https://gitee.com/{repo}/releases/download/data-latest/snapshot-manifest.json")
        response.raise_for_status()
        manifest = response.json()
        for path in paths:
            if manifest.get("files", {}).get(path.name, {}).get("sha256") != digest_file(path):
                raise ValueError(f"{path.name} 不是本次本地快照")
        verify_manifest(client, repo, "data-latest", manifest)
    print("OK：全部镜像文件匿名下载、分片连续性与SHA256校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
