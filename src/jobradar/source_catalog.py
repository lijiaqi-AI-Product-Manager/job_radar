"""随软件分发的来源分类；配置声明与实时可用性分别展示。"""

import json
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "_data" / "source_catalog.json"
NOTICE_ADAPTERS = {"campus", "jysd"}


def build_catalog(sources):
    result = {}
    for source in sorted(sources, key=lambda source: source.id):
        if source.id in result:
            raise ValueError(f"重复 source id: {source.id}")
        result[source.id] = {
            "source_kind": source.source_kind,
            "record_kind": "recruitment_notice"
            if source.adapter in NOTICE_ADAPTERS
            else "position",
            "adapter": source.adapter,
            "compliance_checked_on": source.compliance.checked_on.isoformat()
            if source.compliance
            else None,
            "enabled": source.enabled,
        }
    return result


@lru_cache(maxsize=1)
def catalog():
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # 来源晚于客户端目录时保持 unknown，不根据名称或域名猜测。
