"""公司简称 → 库中全名（映射表：taxonomy/company_aliases.yaml）。

用户会说「中核」「中船」「国寿」，库里存的是「中国核工业集团」「中国船舶集团」「中国人寿」。
`search --company` 只做子串匹配，简称会查不到（2026-10-22 评测 neg-05）。

规则：只用映射表，不做模糊猜测；表里没有的简称保持原样（查不到就如实说没有）。
以库的形式安装时没有 taxonomy 目录，此时退化为"只匹配原词"。
"""

from functools import cache
from pathlib import Path

import yaml

PATH = Path(__file__).resolve().parents[2] / "taxonomy" / "company_aliases.yaml"


@cache
def _aliases() -> dict[str, str]:
    if not PATH.exists():
        return {}
    doc = yaml.safe_load(PATH.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (doc.get("aliases") or {}).items()}


def match_names(term: str) -> list[str]:
    """返回用于 LIKE 匹配的名称：原词 + 简称对应的全名（去重、保持顺序）。"""
    term = term.strip()
    names = [term]
    full = _aliases().get(term)
    if full and full not in names:
        names.append(full)
    return names
