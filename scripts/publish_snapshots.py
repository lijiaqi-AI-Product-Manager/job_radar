"""先上传不可变压缩文件，再原子提交Release清单，最后更新旧客户端别名。"""

import argparse
import base64
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from time import sleep

from jobradar.snapshot_manifest import digest_file
from jobradar.store.validate import validate_database

REPO = "lijiaqi-AI-Product-Manager/job_radar"
ROOT = Path(__file__).resolve().parents[1]
FILES = ("jobs.db.gz", "jd_text.db.gz", "calendar.db.gz")
ALIASES = (*FILES, "jobs.db", "jd_text.db", "calendar.db")


def make_manifest(home):
    files = {}
    for name in FILES:
        path = home / name
        sha = digest_file(path)
        files[name] = {"sha256": sha, "size": path.stat().st_size, "asset": sha[:20] + "-" + name}
    generation = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:20]
    manifest = {"version": 1, "generation": generation, "files": files}
    compact = home / "jd_text.compact.db.gz"
    if compact.is_file():
        sha = digest_file(compact)
        manifest["variants"] = {"text_compact":{"version":1,"sha256":sha,"size":compact.stat().st_size,
            "asset":sha[:20]+"-"+compact.name,"source_sha256":files["jd_text.db.gz"]["sha256"]}}
    return manifest


def publication_items(manifest):
    items = list(manifest["files"].items())
    if manifest.get("variants"):
        items.append(("jd_text.compact.db.gz",manifest["variants"]["text_compact"]))
    return items


def gh(*args, capture=False):
    result = subprocess.run(["gh", *args], check=True, capture_output=capture, text=True, encoding="utf-8")
    return json.loads(result.stdout) if capture else None


def publish_aliases(home, names=ALIASES):
    """逐个核对兼容附件；瞬时失败后先复查，避免删除已经完成的文件。"""
    names = tuple(names)
    if set(names) - set(ALIASES):
        raise ValueError("兼容发布只允许固定历史文件名")
    local = [(home / name, digest_file(home / name), (home / name).stat().st_size) for name in names]
    endpoint = f"repos/{REPO}/releases/tags/data-latest"
    for path, sha, size in local:
        def matches(release, name=path.name, size=size, sha=sha):
            return any(asset.get("name") == name and asset.get("size") == size
                       and asset.get("digest") == "sha256:" + sha for asset in release.get("assets", []))

        for attempt in range(3):
            try:
                if matches(gh("api", endpoint, capture=True)):
                    break
                gh("release", "upload", "data-latest", str(path), "--repo", REPO, "--clobber")
                if not matches(gh("api", endpoint, capture=True)):
                    raise ValueError("远端兼容附件大小或摘要不一致")
                break
            except (subprocess.CalledProcessError, ValueError) as error:
                if attempt == 2:
                    raise RuntimeError(f"兼容附件{path.name}经过3次尝试仍未通过校验") from error
                print(f"::warning::兼容附件{path.name}尚未确认，稍后重新核对并重试", file=sys.stderr)
                sleep(2 ** (attempt + 1))
    return list(names)


def publish(home):
    import sqlite3
    from contextlib import closing

    # 真实质量门禁在任何外部写入之前完成；缺失数据的SKIP也不允许发布。
    subprocess.run([sys.executable, str(ROOT / "scripts/release_check.py"), "--home", str(home)], check=True)
    for kind, name in (("jobs", "jobs.db"), ("text", "jd_text.db"), ("calendar", "calendar.db")):
        with closing(sqlite3.connect((home / name).resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            validate_database(conn, kind)
    from jobradar.compact_text import export_compact_text
    export_compact_text(home/"jd_text.db",home/"jd_text.compact.db")
    with (home/"jd_text.compact.db").open("rb") as source, (home/"jd_text.compact.db.gz").open("wb") as output:
        with gzip.GzipFile(filename="",mode="wb",fileobj=output,mtime=0,compresslevel=9) as compressed:
            shutil.copyfileobj(source,compressed)
    manifest = make_manifest(home)
    endpoint = f"repos/{REPO}/releases/tags/data-latest"
    previous = gh("api", endpoint, capture=True)
    assets = {a["name"]: a for a in previous.get("assets", [])}
    with tempfile.TemporaryDirectory(prefix="snapshot-publish-", dir=home.parent) as directory:
        staging = Path(directory)
        pending = []
        for name, item in publication_items(manifest):
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
        for _,item in publication_items(manifest):
            if actual.get(item["asset"], {}).get("digest") != "sha256:" + item["sha256"]:
                raise ValueError("远端不可变文件摘要校验失败，尚未切换清单")
        marker = base64.b64encode(json.dumps(manifest, sort_keys=True).encode()).decode()
        notes = staging / "notes.md"
        notes.write_text("# Latest verified data\n\n中国招聘岗位、JD正文与招聘日历；三库通过真实数据门禁后成套发布。\n\n"
                         "旧文件名供历史客户端使用；新版客户端按完整性清单读取不可变文件。\n\n"
                         f"<!--jobradar-snapshot:{marker}-->\n", encoding="utf-8")
        gh("release", "edit", "data-latest", "--repo", REPO, "--notes-file", str(notes), "--latest=false")
        # 新客户端已使用完整不可变代；旧客户端文件名继续分发兼容schema。
        aliases = publish_aliases(home)
    print(json.dumps({"published_generation": manifest["generation"], "verified_files": list(manifest["files"]),
                      "verified_aliases": aliases}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args()
    publish(args.home)


if __name__ == "__main__":
    main()
