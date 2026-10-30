"""发布可兼容既有客户端的数据库副本，全文索引由新客户端在本地重建。"""

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

_FORMATS = {'jobs': (2, 3, 'job_fts'), 'text': (1, 2, 'job_text_fts')}


def export_database(source: Path, target: Path, kind: str) -> None:
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or kind not in _FORMATS:
        raise ValueError('export requires a separate destination and a supported database kind')
    baseline, latest, index = _FORMATS[kind]
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.db', delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
            version = original.execute('PRAGMA user_version').fetchone()[0]
            if version not in {baseline, latest}:
                raise ValueError(f'unsupported {kind} schema for public export: {version}')
            with closing(sqlite3.connect(temporary)) as published:
                original.backup(published)
                with published:
                    for suffix in ('insert', 'update', 'delete'):
                        published.execute(f'DROP TRIGGER IF EXISTS {index}_{suffix}')
                    published.execute(f'DROP TABLE IF EXISTS {index}')
                    published.execute(f'PRAGMA user_version={baseline}')
                published.execute('VACUUM')
                if published.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('public database failed integrity verification')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
