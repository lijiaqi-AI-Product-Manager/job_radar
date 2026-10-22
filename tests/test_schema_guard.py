"""强制执行"不允许改 schema 除非更新迁移"。

- 已登记的迁移文件被改动 -> 失败（要改 schema 就新增迁移，不要改旧文件）
- 新增了迁移文件却没登记 -> 失败（运行 scripts/update_schema_lock.py）
"""

import json
from pathlib import Path

import pytest

from jobradar.store.migrate import KINDS, migration_digest, migration_files

LOCK = Path(__file__).parent / "schema_lock.json"


def sha(path: Path) -> str:
    return migration_digest(path)


def test_digest_ignores_line_endings(tmp_path):
    """Windows checkout 会把 LF 转成 CRLF，哈希不能因此变化（Windows CI 实际踩到）。"""
    lf = tmp_path / "lf.sql"
    crlf = tmp_path / "crlf.sql"
    lf.write_bytes(b"select 1;\nselect 2;\n")
    crlf.write_bytes(b"select 1;\r\nselect 2;\r\n")
    assert migration_digest(lf) == migration_digest(crlf)


@pytest.fixture(scope="module")
def lock():
    return json.loads(LOCK.read_text())


@pytest.mark.parametrize("kind", KINDS)
def test_applied_migrations_are_immutable(kind, lock):
    for f in migration_files(kind):
        recorded = lock.get(kind, {}).get(f.name)
        if recorded is not None:
            assert sha(f) == recorded, (
                f"{kind}/{f.name} 已登记，不能修改。请新增下一个编号的迁移文件。"
            )


@pytest.mark.parametrize("kind", KINDS)
def test_every_migration_is_registered(kind, lock):
    missing = [f.name for f in migration_files(kind) if f.name not in lock.get(kind, {})]
    assert not missing, f"未登记的迁移 {missing}：运行 `uv run python scripts/update_schema_lock.py`"


@pytest.mark.parametrize("kind", KINDS)
def test_no_registered_migration_was_deleted(kind, lock):
    present = {f.name for f in migration_files(kind)}
    assert set(lock.get(kind, {})) <= present, "不允许删除已登记的迁移"
