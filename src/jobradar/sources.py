"""加载 sources/*.yaml。

文件格式二选一：
  1) 单个源：直接写 SourceConfig 字段
  2) 批量（平台型，一行一家公司）：
       defaults: {adapter: moka, recruit_types: [campus], compliance: {...}}
       sources:
         - {id: moka-acme, company: 某公司, params: {org: acme}}
文件名以 _ 开头的被忽略（示例文件）。
"""

from pathlib import Path

import yaml

from jobradar.models import SourceConfig

KNOWN_FIELDS = frozenset(SourceConfig.model_fields)


def _merge(defaults: dict, entry: dict) -> dict:
    merged = {**defaults, **entry}
    if "params" in defaults or "params" in entry:
        merged["params"] = {**defaults.get("params", {}), **entry.get("params", {})}
    # 顶格写了未知字段 = 配置静默失效（2026-10-23 踩过：11 个源把 max_pages 写在顶层，
    # 而 SourceConfig.max_pages 读的是 params["max_pages"]，于是限额全部没生效，星巴克一次抓了 18418 岗）
    unknown = set(merged) - KNOWN_FIELDS
    if unknown:
        hint = "；max_pages 这类适配器参数要写在 params 里" if "max_pages" in unknown else ""
        raise ValueError(f"source {merged.get('id') or '?'}: 未知字段 {sorted(unknown)}{hint}")
    return merged


def parse_file(path: Path) -> list[SourceConfig]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "sources" in doc:
        defaults = doc.get("defaults", {})
        return [SourceConfig(**_merge(defaults, e)) for e in doc["sources"]]
    return [SourceConfig(**doc)]


def load_sources(directory: Path, *, include_examples: bool = False) -> list[SourceConfig]:
    out: list[SourceConfig] = []
    for p in sorted(Path(directory).rglob("*.yaml")):
        if p.name.startswith("_") and not include_examples:
            continue
        out.extend(parse_file(p))
    return out
