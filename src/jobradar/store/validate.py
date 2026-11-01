"""按不可变迁移核验下载数据库，不信任文件头或自行声明的版本号。"""

import re
import sqlite3
from contextlib import closing
from functools import cache

from jobradar.store.migrate import migration_files


def _constraints(conn, name):
    unique = {tuple(r[2] for r in conn.execute(f'PRAGMA index_info("{index[1]}")'))
              for index in conn.execute(f'PRAGMA index_list("{name}")') if index[2]}
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0] or ""
    # 当前不可变迁移的CHECK均为标量IN；保留字符串内容，仅归一SQL空白。
    checks = {re.sub(r"\s+", "", match).lower() for match in re.findall(r"\bCHECK\s*\(([^)]+)\)", sql, re.I)}
    return unique, checks


@cache
def _contract(kind, version):
    with closing(sqlite3.connect(":memory:")) as reference:
        for path in migration_files(kind)[:version]:
            reference.executescript(path.read_text(encoding="utf-8"))
        tables = {}
        for (name,) in reference.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if name.startswith("sqlite_"):
                continue
            columns = {r[1]: (r[2].upper(), r[3], r[5]) for r in reference.execute(f'PRAGMA table_info("{name}")')}
            foreign = [tuple(r)[2:] for r in reference.execute(f'PRAGMA foreign_key_list("{name}")')]
            tables[name] = (columns, foreign, _constraints(reference, name))
        return tables


def validate_database(conn, kind):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    latest = len(migration_files(kind))
    if not 1 <= version <= latest:
        raise ValueError(f"不支持的 {kind} schema: {version}")
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = _contract(kind, version)
    # 兼容导出可以保留后续版本的独立证据表；已存在时也必须核验其完整结构。
    optional = {name: value for name, value in _contract(kind, latest).items()
                if name not in required and name in present and "_fts" not in name}
    for name, (columns, foreign, constraints) in {**required, **optional}.items():
        if name not in present:
            raise ValueError(f"缺少 {kind}.{name}")
        actual = {r[1]: (r[2].upper(), r[3], r[5]) for r in conn.execute(f'PRAGMA table_info("{name}")')}
        if any(actual.get(key) != value for key, value in columns.items()):
            raise ValueError(f"{kind}.{name} 列契约不匹配")
        if sorted(tuple(r)[2:] for r in conn.execute(f'PRAGMA foreign_key_list("{name}")')) != sorted(foreign):
            raise ValueError(f"{kind}.{name} 外键契约不匹配")
        actual_unique, actual_checks = _constraints(conn, name)
        if not constraints[0] <= actual_unique or not constraints[1] <= actual_checks:
            raise ValueError(f"{kind}.{name} 唯一性或CHECK约束不匹配")
    if conn.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
        raise ValueError("数据库完整性校验失败")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("数据库外键关联不完整")
    arrays = {"jobs": (("job", "cities"),), "text": (),
              "calendar": (("entry", "cities"), ("entry", "tracks"), ("target", "data_companies"))}
    for table, column in arrays[kind]:
        if conn.execute(f'SELECT 1 FROM "{table}" WHERE NOT json_valid("{column}") '
                        f'OR json_type("{column}") != \'array\' LIMIT 1').fetchone():
            raise ValueError(f"{table}.{column} 不是 JSON 数组")
    if kind == "calendar" and "entry_field_evidence" in present:
        if conn.execute("SELECT 1 FROM entry_field_evidence WHERE NOT json_valid(fields) "
                        "OR json_type(fields) != 'object' LIMIT 1").fetchone():
            raise ValueError("字段证据不是JSON对象")
