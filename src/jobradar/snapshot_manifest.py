"""不可变数据代的文件清单与匿名字节校验。"""

import hashlib
import re


def digest_file(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_manifest(client, repo, tag, manifest):
    if not re.fullmatch(r"data-(?:[a-f0-9]{20}|latest)", tag):
        raise ValueError("非法数据代标签")
    if manifest.get("version") != 1 or not manifest.get("files"):
        raise ValueError("无效数据清单")
    for name, info in manifest["files"].items():
        if not re.fullmatch(r"(?:jobs\.db\.gz|jd_text\.db\.gz|calendar\.db\.gz|crawl-summary\.json)", name):
            raise ValueError("非法快照文件名")
        combined, size = hashlib.sha256(), 0
        for index, part in enumerate(info["parts"], 1):
            expected_name = name if len(info["parts"]) == 1 else f"{name}.part{index:02d}"
            if part["name"] != expected_name:
                raise ValueError("分片序号不连续")
            actual, count = hashlib.sha256(), 0
            url = f"https://gitee.com/{repo}/releases/download/{tag}/{part['name']}"
            with client.stream("GET", url, follow_redirects=True) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    actual.update(chunk)
                    combined.update(chunk)
                    count += len(chunk)
            if count != part["size"] or actual.hexdigest() != part["sha256"]:
                raise ValueError(f"{part['name']} 匿名下载摘要不匹配")
            size += count
        if size != info["size"] or combined.hexdigest() != info["sha256"]:
            raise ValueError(f"{name} 拼接摘要不匹配")
