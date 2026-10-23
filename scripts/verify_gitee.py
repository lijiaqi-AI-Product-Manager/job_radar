"""校验 Gitee 镜像上每个文件的大小与本地一致（防止"假成功"：拿到的其实是旧文件）。

大文件在镜像侧可能是分片（`<name>.part01`…，见 publish_gitee.py），所以：
先按整文件比大小；404 就按分片求和；两者都没有 → 失败。

用法：python scripts/verify_gitee.py <本地文件> [<本地文件> ...]
环境变量：GITEE_REPO（owner/repo）
"""

import os
import sys
from pathlib import Path

import httpx

BASE = "https://gitee.com/{repo}/releases/download/data-latest/{name}"
MAX_PARTS = 99


def remote_size(client: httpx.Client, repo: str, name: str) -> int | None:
    """整文件存在返回其大小，否则 None。"""
    url = BASE.format(repo=repo, name=name)
    r = client.get(url, follow_redirects=True)
    if r.status_code != 200:
        return None
    return int(r.headers.get("content-length") or len(r.content))


def parts_size(client: httpx.Client, repo: str, name: str) -> tuple[int, int]:
    """返回 (分片总字节数, 分片数)。"""
    total, count = 0, 0
    for idx in range(1, MAX_PARTS + 1):
        url = BASE.format(repo=repo, name=f"{name}.part{idx:02d}")
        r = client.get(url, follow_redirects=True)
        if r.status_code != 200:
            break
        total += int(r.headers.get("content-length") or len(r.content))
        count += 1
    return total, count


def main() -> int:
    repo = os.environ.get("GITEE_REPO", "qgauss/job_radar")
    files = [Path(p) for p in sys.argv[1:]]
    if not files:
        print("no files given", file=sys.stderr)
        return 2
    bad = 0
    with httpx.Client(headers={"User-Agent": "jobradar"}, timeout=120) as client:
        for f in files:
            expected = f.stat().st_size
            got = remote_size(client, repo, f.name)
            if got is None:
                got, n = parts_size(client, repo, f.name)
                kind = f"{n} 片"
            else:
                kind = "整文件"
            ok = got == expected
            bad += 0 if ok else 1
            print(f"{'OK ' if ok else 'BAD'} {f.name}: gitee={got}B local={expected}B ({kind})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
