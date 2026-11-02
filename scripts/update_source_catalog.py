"""重建安装包使用的来源分类目录；只输出固定白名单字段。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.source_catalog import CATALOG_PATH, build_catalog  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def main():
    entries = build_catalog(load_sources(ROOT / "sources"))
    CATALOG_PATH.parent.mkdir(exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"source catalog: {len(entries)} entries")


if __name__ == "__main__":
    main()
