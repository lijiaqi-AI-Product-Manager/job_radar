"""随软件分发的来源分类；配置声明与实时可用性分别展示。"""

import json
from collections import defaultdict
from functools import lru_cache
from itertools import combinations
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "_data" / "source_catalog.json"
NOTICE_ADAPTERS = {"campus", "jysd"}


def tenant_key(source):
    """仅识别配置明确声明的平台租户，不由公司名或岗位重合猜测归属。"""
    if source.adapter == "hotjob":
        value = source.params.get("tenant")
    elif source.adapter == "beisen":
        value = source.params.get("host") or (
            f"{source.params['tenant']}.zhiye.com" if source.params.get("tenant") else None)
    else:
        return None
    return (source.adapter, value.strip().rstrip(".").casefold()) if isinstance(value, str) and value.strip() else None


def _tenant_pairs(sources):
    groups = defaultdict(list)
    for source in sorted(sources, key=lambda item:item.id):
        if key := tenant_key(source):
            groups[key].append(source)
    for group in groups.values():
        for a, b in combinations(group, 2):
            if set(a.recruit_types) & set(b.recruit_types):
                yield a, b


def duplicate_enabled_tenants(sources):
    return [[a.id,b.id] for a,b in _tenant_pairs(sources) if a.enabled and b.enabled]


def build_catalog(sources):
    sources = list(sources)
    peers = defaultdict(list)
    for a,b in _tenant_pairs(sources):
        peers[a.id].append(b.id)
        peers[b.id].append(a.id)
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
        if peers[source.id]:
            result[source.id]["tenant_peers"] = sorted(peers[source.id])
    return result


@lru_cache(maxsize=1)
def catalog():
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # 来源晚于客户端目录时保持 unknown，不根据名称或域名猜测。
