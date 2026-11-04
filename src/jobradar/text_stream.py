"""正文传输流：整流压缩减少下载，在本地重建原有只读精简库。"""

import hashlib
import json
import lzma
import os
import sqlite3
import tempfile
import zlib
from contextlib import closing
from itertools import zip_longest
from pathlib import Path

from jobradar.compact_text import MAX_BODY_BYTES, _decode, is_compact_text
from jobradar.store.migrate import connect
from jobradar.store.validate import validate_database
from jobradar.timeutil import parse_ts

MAX_STREAM_RECORD = MAX_BODY_BYTES + 8192
MAX_STREAM_BYTES = 4 * 1024 ** 3
MAX_STREAM_ROWS = 10_000_000
STREAM_MEMORY = 64 * 1024 ** 2


def _lines(path):
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=STREAM_MEMORY)
    pending, total = bytearray(), 0
    with Path(path).open('rb') as incoming:
        while not decoder.eof:
            chunk = incoming.read(65536) if decoder.needs_input else b''
            if decoder.needs_input and not chunk:
                raise ValueError('正文传输流被截断')
            block = decoder.decompress(chunk, max_length=65536)
            total += len(block)
            if total > MAX_STREAM_BYTES:
                raise ValueError('正文传输流超过大小上限')
            pending.extend(block)
            start = 0
            while (end := pending.find(b'\n', start)) >= 0:
                if end - start > MAX_STREAM_RECORD:
                    raise ValueError('正文传输记录超过大小上限')
                yield json.loads(pending[start:end])
                start = end + 1
            del pending[:start]
            if len(pending) > MAX_STREAM_RECORD:
                raise ValueError('正文传输记录超过大小上限')
        if (pending or decoder.unused_data or incoming.read(1)
                or decoder.check not in (lzma.CHECK_CRC64, lzma.CHECK_SHA256)):
            raise ValueError('正文传输流尾部或校验格式无效')


def _count(value):
    return type(value) is int and 0 <= value <= MAX_STREAM_ROWS


def export_text_stream(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError('正文传输导出必须使用独立路径')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as conn:
            if not is_compact_text(conn):
                raise ValueError('正文传输导出需要已核验的精简库')
            validate_database(conn, 'text')
            bodies = conn.execute('SELECT COUNT(*) FROM jd_body').fetchone()[0]
            refs = conn.execute('SELECT COUNT(*) FROM jd_ref').fetchone()[0]
            if not _count(bodies) or not _count(refs):
                raise ValueError('正文传输记录数超过上限')
            with lzma.open(temporary, 'wb', preset=3) as stream:
                stream.write(json.dumps(['jobradar-text-stream', 1, bodies, refs]).encode() + b'\n')
                for body_id, payload in conn.execute('SELECT id,payload FROM jd_body ORDER BY id'):
                    stream.write(b'["b",' + str(body_id).encode() + b',' + _decode(payload).encode('utf-8') + b']\n')
                for job_id, body_id, stamp in conn.execute('SELECT job_id,body_id,fetched_at FROM jd_ref ORDER BY job_id'):
                    record = ['r', job_id, body_id, stamp]
                    stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n')
                stream.write(json.dumps(['end', bodies, refs]).encode() + b'\n')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def import_text_stream(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError('正文传输导入必须使用独立路径')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.db', delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(_lines(source)) as records, closing(connect(temporary, 'text_compact')) as conn:
            header = next(records, None)
            if (not isinstance(header, list) or len(header) != 4 or header[:2] != ['jobradar-text-stream', 1]
                    or type(header[1]) is not int
                    or not _count(header[2]) or not _count(header[3])):
                raise ValueError('正文传输流头部无效')
            bodies, refs = header[2:]
            conn.execute('PRAGMA foreign_keys=ON')
            with conn:
                for _ in range(bodies):
                    row = next(records, None)
                    if (not isinstance(row, list) or len(row) != 3 or row[0] != 'b'
                            or type(row[1]) is not int or not 0 < row[1] <= 2 ** 63 - 1
                            or not isinstance(row[2], list) or len(row[2]) != 2
                            or any(value is not None and not isinstance(value, str) for value in row[2])):
                        raise ValueError('正文传输内容无效')
                    raw = json.dumps(row[2], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                    if len(raw) > MAX_BODY_BYTES:
                        raise ValueError('正文内容超过上限')
                    conn.execute('INSERT INTO jd_body(id,digest,payload) VALUES (?,?,?)',
                                 (row[1], hashlib.sha256(raw).digest(), zlib.compress(raw, 9)))
                for _ in range(refs):
                    row = next(records, None)
                    if (not isinstance(row, list) or len(row) != 4 or row[0] != 'r'
                            or not isinstance(row[1], str) or not 0 < len(row[1]) <= 4096
                            or type(row[2]) is not int or not 0 < row[2] <= 2 ** 63 - 1
                            or not isinstance(row[3], str) or not 0 < len(row[3]) <= 64):
                        raise ValueError('正文岗位关联无效')
                    parse_ts(row[3])
                    conn.execute('INSERT INTO jd_ref VALUES (?,?,?)', tuple(row[1:]))
                if next(records, None) != ['end', bodies, refs] or next(records, None) is not None:
                    raise ValueError('正文传输记录数或结束标记无效')
            conn.execute('VACUUM')
            validate_database(conn, 'text')
        os.replace(temporary, target)
    except (lzma.LZMAError, sqlite3.DatabaseError, UnicodeError) as error:
        raise ValueError('正文传输流损坏或格式无效') from error
    finally:
        temporary.unlink(missing_ok=True)


def verify_text_stream(source, archive):
    with tempfile.TemporaryDirectory(prefix='text-stream-check-', dir=Path(archive).parent) as directory:
        imported = Path(directory) / 'jd_text.db'
        import_text_stream(archive, imported)
        with closing(connect(source, 'text')) as before, closing(connect(imported, 'text')) as after:
            with closing(before.execute('SELECT * FROM job_text ORDER BY job_id')) as a, \
                    closing(after.execute('SELECT * FROM job_text ORDER BY job_id')) as b:
                for old, new in zip_longest(a, b):
                    if old is None or new is None or tuple(old) != tuple(new):
                        raise ValueError('正文传输往返记录不一致')
