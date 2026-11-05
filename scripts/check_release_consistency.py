"""发行前核对版本、介绍、构建元数据及同一代公开数据。"""

import argparse
import base64
import json
import re
import tarfile
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx

from jobradar import __version__

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/lijiaqi-AI-Product-Manager/job_radar"


def text(path):
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def has_number(body, number):
    forms = {
        str(number),
        f"{number:,}",
        f"{number:,}".replace(",", "."),
        f"{number:,}".replace(",", " "),
    }
    return any(re.search(r"(?<![0-9])" + re.escape(value) + r"(?![0-9])", body) for value in forms)


def validate(root, version):
    target = json.loads(text(root / "docs/install-target.json"))
    if target["version"] != version or target["revision"] != "v" + version:
        raise ValueError("安装目标与发行版本不一致")
    if not re.search(
        r"^## " + re.escape(version) + r"(?: —[^\n]+)?$", text(root / "CHANGELOG.md"), re.M
    ):
        raise ValueError("当前版本缺少变更记录")
    snapshot = json.loads(text(root / "docs/release-snapshot.json"))
    if not re.fullmatch("[a-f0-9]{20}", snapshot["generation"]):
        raise ValueError("快照代号无效")
    for key in ("total_jobs", "visible_jobs", "calendar_entries", "calendar_manual"):
        if type(snapshot[key]) is not int or snapshot[key] <= 0:
            raise ValueError("快照统计无效")
    if (
        snapshot["visible_jobs"] > snapshot["total_jobs"]
        or snapshot["calendar_manual"] > snapshot["calendar_entries"]
    ):
        raise ValueError("快照统计分母不一致")
    for path in [*root.glob("README*.md"), root / "docs/COVERAGE.md"]:
        body = text(path)
        if not all(has_number(body, snapshot[k]) for k in ("total_jobs", "visible_jobs")):
            raise ValueError(f"{path.name}岗位统计与快照不一致")
        if (
            path.name in {"README.md", "README.en.md", "COVERAGE.md"}
            and snapshot["data_as_of"] not in body
        ):
            raise ValueError(f"{path.name}数据时间不一致")
        if path.name in {"README.md", "COVERAGE.md"} and not all(
            has_number(body, snapshot[k]) for k in ("calendar_entries", "calendar_manual")
        ):
            raise ValueError("日历口径不一致")
    return snapshot


def validate_artifacts(root, directory, version):
    expected = text(root / "README.md")
    with zipfile.ZipFile(directory / f"jobsearchradar-{version}-py3-none-any.whl") as wheel:
        names = [n for n in wheel.namelist() if n.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("wheel元数据不唯一")
        meta = BytesParser(policy=policy.default).parsebytes(wheel.read(names[0]))
        if (
            meta["Name"] != "jobsearchradar"
            or meta["Version"] != version
            or meta.get_payload(decode=True).decode("utf-8").replace("\r\n", "\n") != expected
        ):
            raise ValueError("wheel版本或README与源码不一致")
    with tarfile.open(directory / f"jobsearchradar-{version}.tar.gz") as archive:
        data = archive.extractfile(f"jobsearchradar-{version}/README.md").read().decode("utf-8-sig")
        if data.replace("\r\n", "\n") != expected:
            raise ValueError("源码包README不一致")


def verify_online(root, snapshot, client):
    def get(url):
        r = client.get(url)
        r.raise_for_status()
        return r.json()

    readme = get(API + "/contents/README.md?ref=main")
    if readme.get("encoding") != "base64" or base64.b64decode(readme["content"]).decode(
        "utf-8-sig"
    ).replace("\r\n", "\n") != text(root / "README.md"):
        raise ValueError("GitHub main介绍已变化，需要重新准备发行")
    release = get(API + "/releases/tags/data-latest")
    marker = re.search(r"<!--jobradar-snapshot:(.*?)-->", release.get("body", ""), re.S)
    if marker is None:
        raise ValueError("公开数据清单缺失")
    manifest = json.loads(base64.b64decode(marker[1]))
    if manifest["generation"] != snapshot["generation"]:
        raise ValueError("公开数据已换代，请先同步介绍和统计")
    url = (
        "https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/download/data-latest/preservation-"
        + snapshot["generation"]
        + ".json"
    )
    proof = get(url)
    if (
        proof["snapshot_generation"] != snapshot["generation"]
        or proof["data_as_of"] != snapshot["data_as_of"]
    ):
        raise ValueError("快照证据时间或代号不一致")
    if any(
        proof["statistics"][k] != snapshot[k]
        for k in ("total_jobs", "visible_jobs", "calendar_entries", "calendar_manual")
    ):
        raise ValueError("公开快照证据与介绍统计不一致")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    snapshot = validate(ROOT, __version__)
    if args.dist:
        validate_artifacts(ROOT, args.dist, __version__)
    if args.online:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            verify_online(ROOT, snapshot, client)
    print("发行版本、README与数据口径一致")


if __name__ == "__main__":
    main()
