"""登记新增的迁移文件到 tests/schema_lock.json。已登记文件的哈希不会被改写；若它们被改动则报错。"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.store.migrate import KINDS, migration_files  # noqa: E402

LOCK = ROOT / "tests" / "schema_lock.json"


def main() -> int:
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    for kind in KINDS:
        entries = lock.setdefault(kind, {})
        for f in migration_files(kind):
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            if f.name in entries and entries[f.name] != digest:
                print(f"ERROR: {kind}/{f.name} 已登记但内容被改动。请还原它并新增迁移。")
                return 1
            if f.name not in entries:
                entries[f.name] = digest
                print(f"registered {kind}/{f.name}")
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
