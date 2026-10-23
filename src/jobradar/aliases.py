"""公司简称 → 库中全名（映射表：taxonomy/company_aliases.yaml）。

用户会说「中核」「中船」「国寿」，库里存的是「中国核工业集团」「中国船舶集团」「中国人寿」。
`search --company` 首先做全等匹配，简称会查不到（2026-10-22 评测 neg-05），所以需要这张表。

规则：只用映射表，不做模糊猜测；表里没有的简称保持原样（查不到就如实说没有）。

映射表的两个位置：
- `taxonomy/company_aliases.yaml`：源码/仓库里跑（也是唯一维护处）
- `jobradar/_data/company_aliases.yaml`：wheel 里的副本（hatch 的 force-include 打进包，
  否则 pip 装完就没有 taxonomy 目录，简称映射在真实用户那里等于没启用）
"""

from functools import cache
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()


def _candidates() -> tuple[Path, ...]:
    return (
        _HERE.parents[2] / "taxonomy" / "company_aliases.yaml",   # 源码树
        _HERE.parent / "_data" / "company_aliases.yaml",           # wheel
    )


def _path() -> Path | None:
    return next((p for p in _candidates() if p.exists()), None)


PATH = _candidates()[0]  # 兼容旧引用；实际读取用 _path()


@cache
def _aliases() -> dict[str, str]:
    path = _path()
    if path is None:
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (doc.get("aliases") or {}).items()}


def match_names(term: str) -> list[str]:
    """返回同名候选：原词 + 简称对应的全名（去重、保持顺序）。"""
    term = term.strip()
    names = [term]
    full = _aliases().get(term)
    if full and full not in names:
        names.append(full)
    return names
