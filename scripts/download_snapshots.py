"""下载同一已提交清单的数据；供恢复和镜像使用，不读取可变别名的混合代。"""

import argparse
import hashlib
import json
from pathlib import Path

import httpx

from jobradar.cli import _download, _fetch
from jobradar.local import DB_FILES, github_url, remote_digests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compressed", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    digests = remote_digests(timeout=30)
    if not digests:
        raise SystemExit("无法核实远端清单，停止恢复/镜像")
    with httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=True) as client:
        for name in DB_FILES.values():
            if not args.compressed:
                _download(name, args.out / name, client=client, prefer="github", digests=digests)
                continue
            asset = name + ".gz"
            remote_name = getattr(digests, "asset_names", {}).get(asset, asset)
            temporary = _fetch(client, github_url(remote_name), {}, args.out)
            if temporary is None:
                raise ValueError(f"{asset} 缺失")
            with temporary.open("rb") as handle:
                sha = "sha256:" + hashlib.file_digest(handle, "sha256").hexdigest()
            if sha != digests.get(asset):
                temporary.unlink(missing_ok=True)
                raise ValueError(f"{asset} 摘要不一致")
            temporary.replace(args.out / asset)
    (args.out / "download-manifest.json").write_text(json.dumps(dict(digests)), encoding="utf-8")


if __name__ == "__main__":
    main()
