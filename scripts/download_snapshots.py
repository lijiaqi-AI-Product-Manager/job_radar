"""下载同一已提交清单的数据；供恢复和镜像使用，不读取可变别名的混合代。"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import httpx

from jobradar.cli import _download, _fetch
from jobradar.local import DB_FILES, REPO, github_url, remote_digests


def first_publication(recorded_snapshot: Path) -> bool:
    if recorded_snapshot.exists():
        return False
    # 只有本地没有发行记录、远端也没有当前或归档快照，才是首次采集。
    tags = subprocess.check_output(
        ["gh", "api", "--paginate", f"repos/{REPO}/releases?per_page=100",
         "--jq", '.[] | select(.tag_name == "data-latest" or .tag_name == "data-archive") | .tag_name'],
        text=True,
    )
    return not tags.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compressed", action="store_true")
    parser.add_argument("--allow-first-publication", action="store_true",
                        help="仓库和发行渠道均无数据历史时，允许建立第一代快照")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    receipt = args.out / "download-manifest.json"
    recorded_snapshot = Path(__file__).resolve().parents[1] / "docs/release-snapshot.json"
    if args.allow_first_publication and first_publication(recorded_snapshot):
        if any(args.out.iterdir()):
            raise SystemExit("首次采集需要空数据目录，已有文件请先核对来源")
        receipt.write_text("{}", encoding="utf-8")
        print("已确认仓库尚无数据快照，开始首次采集")
        return
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
    receipt.write_text(json.dumps(dict(digests)), encoding="utf-8")


if __name__ == "__main__":
    main()
