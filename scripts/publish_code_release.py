"""PyPI摘要通过后，将同一构建的安装包和技能包发布到GitHub代码Release。"""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from time import sleep

import httpx

from jobradar import __version__

ROOT = Path(__file__).resolve().parents[1]
REPO = "lijiaqi-AI-Product-Manager/job_radar"
MAX_FILE_BYTES = 5 * 1024 ** 2


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def distribution_files(directory, skill, version):
    expected = [f"jobsearchradar-{version}-py3-none-any.whl", f"jobsearchradar-{version}.tar.gz"]
    if {path.name for path in Path(directory).iterdir()} != set(expected):
        raise ValueError("发行目录必须只含当前版本的wheel和源码包")
    files = [Path(directory) / name for name in expected]
    skill = Path(skill)
    if skill.name != "jobradar-skill.zip":
        raise ValueError("技能包文件名不正确")
    for path in [*files, skill]:
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
            raise ValueError("发行文件无效或超出容量限制")
    return [*files, skill]


def release_notes(changelog, version):
    headings = list(re.finditer(r"(?m)^## +([^\n]+)$", changelog))
    for index, heading in enumerate(headings):
        if re.fullmatch(r"\[?" + re.escape(version) + r"\]?(?: +[—-].*)?", heading[1]):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
            body = changelog[heading.end():end].strip()
            if body:
                return body
    raise ValueError("CHANGELOG缺少当前正式版本内容")


def wait_for_pypi(files, version, *, client, sleep=sleep, attempts=12):
    expected = {path.name: {"size": path.stat().st_size, "sha256": digest(path)} for path in files}
    url = f"https://pypi.org/pypi/jobsearchradar/{version}/json"
    for attempt in range(attempts):
        try:
            response = client.get(url)
            if response.status_code != 404:
                response.raise_for_status()
                metadata = response.json()
                info = metadata.get("info", {})
                if info.get("name") != "jobsearchradar" or info.get("version") != version:
                    raise ValueError("PyPI项目或版本不一致")
                remote = {item["filename"]: item for item in metadata.get("urls", [])}
                for name, local in expected.items():
                    if name in remote and (remote[name].get("size") != local["size"]
                            or remote[name].get("digests", {}).get("sha256") != local["sha256"]):
                        raise ValueError("PyPI发行文件摘要或大小与当前构建不一致")
                if set(expected) <= set(remote):
                    return
        except httpx.HTTPError:
            pass
        if attempt + 1 < attempts:
            sleep(10)
    raise ValueError("PyPI发行元数据在限定时间内未就绪")


def gh(*args, capture=False):
    result = subprocess.run(["gh", *args], check=True, capture_output=capture, text=True, encoding="utf-8")
    return json.loads(result.stdout) if capture else None


def _release(tag, gh):
    try:
        value = gh("api", f"repos/{REPO}/releases/tags/{tag}", capture=True)
    except subprocess.CalledProcessError as error:
        if "404" in (error.stderr or ""):
            return None
        raise
    if value.get("tag_name") != tag:
        raise ValueError("GitHub版本标签不一致")
    return value


def _asset_state(release, path):
    asset = next((item for item in release["assets"] if item["name"] == path.name), None)
    if asset is None:
        return False
    if asset.get("size") != path.stat().st_size or asset.get("digest") != "sha256:" + digest(path):
        raise ValueError("既有版本附件与当前构建不一致，禁止覆盖")
    return True


def publish_github(files, tag, notes, *, gh=gh, sleep=sleep):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("仅接受固定正式版本标签")
    release = _release(tag, gh)
    if release is None:
        with tempfile.TemporaryDirectory(prefix="jobradar-release-") as folder:
            body = Path(folder) / "notes.md"
            body.write_text(notes, encoding="utf-8")
            try:
                gh("release", "create", tag, "--repo", REPO, "--draft", "--verify-tag",
                   "--title", "job_radar " + tag, "--notes-file", str(body))
            except subprocess.CalledProcessError:
                if _release(tag, gh) is None:
                    raise
        release = _release(tag, gh)
    for path in files:
        for attempt in range(3):
            release = _release(tag, gh)
            if _asset_state(release, path):
                break
            try:
                gh("release", "upload", tag, str(path), "--repo", REPO)
            except subprocess.CalledProcessError:
                pass
            release = _release(tag, gh)
            if _asset_state(release, path):
                break
            if attempt == 2:
                raise ValueError("发行附件经过限定尝试仍未通过核验")
            sleep(2 ** (attempt + 1))
    release = _release(tag, gh)
    if not all(_asset_state(release, path) for path in files):
        raise ValueError("发行附件未完整通过核验")
    if release["draft"]:
        gh("release", "edit", tag, "--repo", REPO, "--draft=false", "--prerelease=false", "--latest")
        if _release(tag, gh)["draft"]:
            raise ValueError("发行仍为草稿，尚未公开")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--skill", type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--check-tag", action="store_true", help="仅检查正式标签，不联网或发布")
    args = parser.parse_args()
    if args.tag != "v" + __version__:
        raise SystemExit("发行标签与代码版本不一致")
    if args.check_tag:
        print("发行标签与代码版本一致")
        return
    if not args.dist or not args.skill:
        parser.error("发布需要--dist及--skill")
    files = distribution_files(args.dist, args.skill, __version__)
    notes = release_notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), __version__)
    checksums = "\n".join(f"| {path.name} | {path.stat().st_size:,} | `{digest(path)}` |" for path in files)
    notes += ("\n\nPython安装包与独立技能包来自同一构建；招聘数据继续通过`jobradar update`获取。"
              "\n\n| 文件 | 字节 | SHA-256 |\n| :--- | ---: | :--- |\n" + checksums + "\n")
    with httpx.Client(timeout=15, headers={"User-Agent": f"jobradar/{__version__}"}) as client:
        wait_for_pypi(files[:2], __version__, client=client)
    publish_github(files, args.tag, notes)
    print(json.dumps({"tag": args.tag, "verified_files": [path.name for path in files]}))


if __name__ == "__main__":
    main()
