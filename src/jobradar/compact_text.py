"""只读正文分发：保留全部逻辑记录，对重复正文做无损压缩，不改工作库。"""

import hashlib
import json
import os
import sqlite3
import tempfile
import zlib
from collections import OrderedDict
from contextlib import closing
from itertools import zip_longest
from pathlib import Path

APPLICATION_ID = 0x4A524354
MAX_BODY_BYTES = 16 * 1024 * 1024
CACHE_BYTES = 4 * 1024 * 1024


def is_compact_text(conn):
    return conn.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID


def _decode(payload):
    if not isinstance(payload, bytes) or len(payload) > MAX_BODY_BYTES:
        raise ValueError("精简正文压缩块无效")
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(payload, MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError("精简正文超过上限或不完整")
        value = json.loads(raw)
        if not isinstance(value, list) or len(value) != 2 or any(v is not None and not isinstance(v, str) for v in value):
            raise ValueError("精简正文字段无效")
        return raw.decode("utf-8")
    except (zlib.error, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("精简正文解压失败") from error


def register_compact_functions(conn):
    """每连接缓存按字节限制，检索不会把整库正文装进内存。"""
    cache, used = OrderedDict(), 0
    def unpack(payload):
        nonlocal used
        if payload in cache:
            value, size = cache.pop(payload)
            cache[payload] = (value, size)
            return value
        value = _decode(payload)
        size = len(payload) + len(value.encode("utf-8"))
        if size <= CACHE_BYTES:
            while cache and used + size > CACHE_BYTES:
                _, (_, removed) = cache.popitem(last=False)
                used -= removed
            cache[payload] = (value, size)
            used += size
        return value
    conn.create_function("jobradar_unpack", 1, unpack, deterministic=True)


def verify_compact_text(conn):
    """核验固定格式、正文摘要及解压边界；未知视图不能冒充精简格式。"""
    from jobradar.store.migrate import migration_files

    register_compact_functions(conn)
    with closing(sqlite3.connect(":memory:")) as expected:
        expected.executescript(migration_files("text_compact")[0].read_text(encoding="utf-8"))
        sql = expected.execute("SELECT sql FROM sqlite_master WHERE name='job_text'").fetchone()[0]
    actual = conn.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='job_text'").fetchone()
    if not actual or "".join(actual[0].split()) != "".join(sql.split()):
        raise ValueError("精简正文逻辑视图不匹配")
    with closing(conn.execute("SELECT digest,payload FROM jd_body")) as bodies:
        for digest, payload in bodies:
            if hashlib.sha256(_decode(payload).encode("utf-8")).digest() != digest:
                raise ValueError("精简正文内容摘要不匹配")


def vacuum_compact_text(conn):
    # 小库保持4KiB页面，避免固定元数据页放大；完整正文库减少页内空闲。
    current = conn.execute('PRAGMA page_size').fetchone()[0]
    live = conn.execute('PRAGMA page_count').fetchone()[0] - conn.execute('PRAGMA freelist_count').fetchone()[0]
    size = 16384 if live * current >= 4 * 1024 ** 2 else 4096
    conn.execute(f'PRAGMA page_size={size}')
    conn.execute('VACUUM')


def export_compact_text(source, target):
    from jobradar.store.migrate import connect
    from jobradar.store.validate import validate_database

    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError("精简导出必须使用独立路径")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".db", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True)) as original, \
                closing(connect(temporary,"text_compact")) as published:
            validate_database(original,"text")
            known = {}
            with published:
                for jid, description, requirements, stamp in original.execute(
                        "SELECT job_id,description,requirements,fetched_at FROM job_text ORDER BY job_id"):
                    raw = json.dumps([description,requirements], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    if len(raw) > MAX_BODY_BYTES:
                        raise ValueError("原始正文超过精简格式上限，保留原数据")
                    digest = hashlib.sha256(raw).digest()
                    body = known.get(digest)
                    if body is None:
                        body = published.execute("INSERT INTO jd_body(digest,payload) VALUES (?,?)",
                                                 (digest,zlib.compress(raw,9))).lastrowid
                        known[digest] = body
                    published.execute("INSERT INTO jd_ref VALUES (?,?,?)",(jid,body,stamp))
            vacuum_compact_text(published)
            validate_database(published,"text")
            with closing(original.execute("SELECT job_id,description,requirements,fetched_at FROM job_text ORDER BY job_id")) as a, \
                    closing(published.execute("SELECT job_id,description,requirements,fetched_at FROM job_text ORDER BY job_id")) as b:
                for before, after in zip_longest(a,b):
                    if before is None or after is None or tuple(before) != tuple(after):
                        raise ValueError("精简正文与原始记录不一致，保留原数据")
        os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)
