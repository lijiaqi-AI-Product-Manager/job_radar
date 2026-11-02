"""SQLite 迁移：migrations/<kind>/NNNN_name.sql 按序执行，版本记在 PRAGMA user_version。

规则（docs/DEVELOPMENT.md 同样写明）：已有迁移文件永远不改；改 schema = 新增下一个编号的迁移文件，
并运行 scripts/update_schema_lock.py 登记。tests/test_schema_guard.py 会强制检查。
"""

import hashlib
import os
import re
import sqlite3
from pathlib import Path

MIGRATIONS_ROOT = Path(__file__).parent / "migrations"
KINDS = ("jobs", "text", "calendar")
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
SEARCH_MIGRATIONS = {"jobs": "0003_add_title_fts.sql", "text": "0002_add_text_fts.sql"}


def migration_digest(path: str | Path) -> str:
    """迁移文件的内容哈希。

    忽略 CRLF/LF 差异：Windows 的 git checkout 默认会把 LF 转成 CRLF，
    不做归一化的话，同一份迁移在 Windows 上算出的哈希与 schema_lock 不符
    （2026-10-22 Windows CI 实际踩到）。
    """
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def migration_files(kind: str) -> list[Path]:
    if kind not in KINDS:
        raise ValueError(f"unknown db kind: {kind}")
    files = sorted((MIGRATIONS_ROOT / kind).glob("*.sql"))
    for i, f in enumerate(files, start=1):
        m = _NAME.match(f.name)
        if not m or int(m.group(1)) != i:
            raise ValueError(f"bad migration name/sequence: {f.name} (expected number {i:04d})")
    return files


def migrate(conn: sqlite3.Connection, kind: str, *, defer_search_index=False) -> int:
    files = migration_files(kind)
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > len(files):
        raise RuntimeError(f"database is newer ({current}) than code ({len(files)}); upgrade jobradar")
    for version, f in enumerate(files[current:], start=current + 1):
        # 只延后末尾的纯索引迁移；未来若有依赖它的结构迁移，仍按完整顺序执行。
        if defer_search_index and version == len(files) and f.name == SEARCH_MIGRATIONS.get(kind):
            break
        conn.executescript(f"BEGIN;\n{f.read_text(encoding='utf-8')}\nPRAGMA user_version={version};\nCOMMIT;")
        current = version
    return current


def connect(path: str | Path, kind: str, *, defer_search_index=False) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn, kind, defer_search_index=defer_search_index)
    return conn


def ensure_search_index(conn: sqlite3.Connection, table: str) -> None:
    """本地全文搜索首次需要时才补建索引；网络盘可禁用补建并走兼容查询。"""
    if os.environ.get("JOBRADAR_BUILD_SEARCH_INDEX", "1").strip() == "0":
        return
    if conn.in_transaction:
        return  # 查询不能隐式提交调用者尚未提交的业务写入。
    kind = {"job_fts": "jobs", "job_text_fts": "text"}.get(table)
    if kind is None:
        return
    files = migration_files(kind)
    # 手工构造的旧连接或未知 schema 不在查询中自动迁移。
    if (files[-1].name == SEARCH_MIGRATIONS[kind]
            and conn.execute("PRAGMA user_version").fetchone()[0] == len(files) - 1):
        migrate(conn, kind)
