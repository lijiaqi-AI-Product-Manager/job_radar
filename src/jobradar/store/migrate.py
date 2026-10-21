"""SQLite 迁移：migrations/<kind>/NNNN_name.sql 按序执行，版本记在 PRAGMA user_version。

规则（CLAUDE.md 同样写明）：已有迁移文件永远不改；改 schema = 新增下一个编号的迁移文件，
并运行 scripts/update_schema_lock.py 登记。tests/test_schema_guard.py 会强制检查。
"""

import re
import sqlite3
from pathlib import Path

MIGRATIONS_ROOT = Path(__file__).parent / "migrations"
KINDS = ("jobs", "text", "calendar")
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def migration_files(kind: str) -> list[Path]:
    if kind not in KINDS:
        raise ValueError(f"unknown db kind: {kind}")
    files = sorted((MIGRATIONS_ROOT / kind).glob("*.sql"))
    for i, f in enumerate(files, start=1):
        m = _NAME.match(f.name)
        if not m or int(m.group(1)) != i:
            raise ValueError(f"bad migration name/sequence: {f.name} (expected number {i:04d})")
    return files


def migrate(conn: sqlite3.Connection, kind: str) -> int:
    files = migration_files(kind)
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > len(files):
        raise RuntimeError(f"database is newer ({current}) than code ({len(files)}); upgrade jobradar")
    for version, f in enumerate(files[current:], start=current + 1):
        conn.executescript(f"BEGIN;\n{f.read_text(encoding='utf-8')}\nPRAGMA user_version={version};\nCOMMIT;")
    return len(files)


def connect(path: str | Path, kind: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn, kind)
    return conn
