"""按发布清单并行下载镜像分片；所有重试共用一个截止时间。"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from jobradar.local import gitee_url


def _file_info(manifest, name, expected):
    try:
        if manifest["version"] != 1 or not re.fullmatch(
            r"data-[a-f0-9]{20}", manifest["generation"]
        ):
            raise ValueError
        info = manifest["files"][name]
        if expected != "sha256:" + info["sha256"] or not re.fullmatch(
            r"[a-f0-9]{64}", info["sha256"]
        ):
            raise ValueError
        parts = info["parts"]
        if not isinstance(parts, list) or not 1 <= len(parts) <= 99:
            raise ValueError
        if type(info["size"]) is not int or not 0 < info["size"] <= 1024**3:
            raise ValueError
        for index, part in enumerate(parts, 1):
            if part["name"] != (name if len(parts) == 1 else f"{name}.part{index:02d}"):
                raise ValueError
            if type(part["size"]) is not int or not 0 < part["size"] <= 128 * 1024**2:
                raise ValueError
            if not re.fullmatch(r"[a-f0-9]{64}", part["sha256"]):
                raise ValueError
        if sum(p["size"] for p in parts) != info["size"]:
            raise ValueError
        return info
    except (KeyError, TypeError, ValueError):
        raise ValueError("镜像分片清单不完整或与本次发布不一致") from None


def fetch_snapshot(client, name, directory, *, expected, fetch, deadline, clock):
    marker = fetch(
        client,
        gitee_url("snapshot-manifest.json"),
        {},
        directory,
        deadline=min(deadline, clock() + 12),
        max_bytes=1024**2,
    )
    if marker is None:
        return None  # 老镜像没有清单时仍可用整份文件摘要验证。
    try:
        manifest = json.loads(marker.read_bytes())
        info = _file_info(manifest, name, expected)
    finally:
        marker.unlink(missing_ok=True)
    stop = threading.Event()
    paths, paths_lock = [], threading.Lock()

    def one_part(part):
        for attempt in range(2):
            if stop.is_set() or clock() >= deadline:
                raise httpx.ReadTimeout("分片下载超过整份文件时间预算")
            piece = None
            try:
                piece = fetch(
                    client,
                    gitee_url(part["name"]),
                    {},
                    directory,
                    deadline=deadline,
                    max_bytes=part["size"],
                )
                if piece is None:
                    raise ValueError("镜像分片缺失")
                with piece.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                if piece.stat().st_size != part["size"] or digest != part["sha256"]:
                    raise ValueError("镜像分片大小或摘要不匹配")
                with paths_lock:
                    paths.append(piece)
                return piece
            except (httpx.HTTPError, ValueError):
                if piece is not None:
                    piece.unlink(missing_ok=True)
                if attempt:
                    stop.set()
                    raise
        raise AssertionError("unreachable")

    fd, temporary = tempfile.mkstemp(dir=directory, suffix=".part")
    joined = Path(temporary)
    try:
        with (
            os.fdopen(fd, "wb") as out,
            ThreadPoolExecutor(max_workers=min(4, len(info["parts"]))) as pool,
        ):
            try:
                for piece in pool.map(one_part, info["parts"]):
                    with piece.open("rb") as handle:
                        shutil.copyfileobj(handle, out)
            except BaseException:
                stop.set()
                raise
        return joined  # 调用方继续核对整份压缩文件摘要、schema 与数据保全条件。
    except BaseException:
        joined.unlink(missing_ok=True)
        raise
    finally:
        for piece in paths:
            piece.unlink(missing_ok=True)
