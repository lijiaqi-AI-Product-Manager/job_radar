"""先上传不可变压缩文件，再原子提交Release清单，最后更新旧客户端别名。"""

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from jobradar.snapshot_manifest import digest_file
from jobradar.store.validate import validate_database

REPO = "lijiaqi-AI-Product-Manager/job_radar"
ROOT = Path(__file__).resolve().parents[1]
FILES = ("jobs.db.gz", "jd_text.db.gz", "calendar.db.gz")


def make_manifest(home):
    files = {}
    for name in FILES:
        path = home / name
        sha = digest_file(path)
        files[name] = {"sha256": sha, "size": path.stat().st_size, "asset": sha[:20] + "-" + name}
    generation = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:20]
    return {"version": 1, "generation": generation, "files": files}


def gh(*args, capture=False):
    result = subprocess.run(["gh", *args], check=True, capture_output=capture, text=True, encoding="utf-8")
    return json.loads(result.stdout) if capture else None


def publish(home):
    import sqlite3
    from contextlib import closing

    # 真实质量门禁在任何外部写入之前完成；缺失数据的SKIP也不允许发布。
    subprocess.run([sys.executable, str(ROOT / "scripts/release_check.py"), "--home", str(home)], check=True)
    for kind, name in (("jobs", "jobs.db"), ("text", "jd_text.db"), ("calendar", "calendar.db")):
        with closing(sqlite3.connect((home / name).resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            validate_database(conn, kind)
    manifest = make_manifest(home)
    endpoint = f"repos/{REPO}/releases/tags/data-latest"
    previous = gh("api", endpoint, capture=True)
    assets = {a["name"]: a for a in previous.get("assets", [])}
    with tempfile.TemporaryDirectory(prefix="snapshot-publish-", dir=home.parent) as directory:
        staging = Path(directory)
        pending = []
        for name, item in manifest["files"].items():
            existing = assets.get(item["asset"])
            if existing:
                if existing.get("digest") != "sha256:" + item["sha256"] or existing["size"] != item["size"]:
                    raise ValueError("已存在不可变文件与清单不一致，禁止覆盖")
            else:
                dest = staging / item["asset"]
                shutil.copyfile(home / name, dest)
                pending.append(str(dest))
        if pending:
            gh("release", "upload", "data-latest", *pending, "--repo", REPO)
        verified = gh("api", endpoint, capture=True)
        actual = {a["name"]: a for a in verified.get("assets", [])}
        for item in manifest["files"].values():
            if actual.get(item["asset"], {}).get("digest") != "sha256:" + item["sha256"]:
                raise ValueError("远端不可变文件摘要校验失败，尚未切换清单")
        marker = base64.b64encode(json.dumps(manifest, sort_keys=True).encode()).decode()
        notes = staging / "notes.md"
        notes.write_text("# Latest verified data\n\n中国招聘岗位、JD正文与招聘日历；三库通过真实数据门禁后成套发布。\n\n"
                         "旧文件名供历史客户端使用；新版客户端按完整性清单读取不可变文件。\n\n"
                         f"<!--jobradar-snapshot:{marker}-->\n", encoding="utf-8")
        gh("release", "edit", "data-latest", "--repo", REPO, "--notes-file", str(notes), "--latest=false")
        # 新客户端已使用完整不可变代；旧客户端文件名继续分发兼容schema。
        aliases = [str(home / name) for name in (*FILES, "jobs.db", "jd_text.db", "calendar.db")]
        gh("release", "upload", "data-latest", *aliases, "--repo", REPO, "--clobber")
    print(json.dumps({"published_generation": manifest["generation"], "verified_files": list(manifest["files"])}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args()
    publish(args.home)


if __name__ == "__main__":
    main()
