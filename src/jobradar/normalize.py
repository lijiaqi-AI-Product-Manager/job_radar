"""从岗位标题等文本中提取校招字段。规则保守：拿不准就返回 None（CLAUDE.md：不要猜）。"""

import re
from functools import cache
from pathlib import Path

import yaml

_GRAD = re.compile(
    r"(?<![\dA-Za-z])(?:20)?(2[4-9]|3[0-2])\s*(?:届|(?:秋季|春季)?(?:校招|校园招聘|秋招|春招|暑期实习|实习))"
)
# 标题开头的【2027】/[27] 这类只写年份的括号
_GRAD_BRACKET = re.compile(r"^\s*[【\[](?:20)?(2[4-9]|3[0-2])[】\]]")
# 顺序即优先级：更具体的批次在前
_BATCHES = (
    ("提前批", ("提前批",)),
    ("补录", ("补录", "补招")),
    ("正式批", ("正式批",)),
    ("春招", ("春招", "春季校园招聘", "春季招聘")),
    ("秋招", ("秋招", "秋季校园招聘", "秋季招聘")),
)


def grad_year_from_text(text: str | None) -> int | None:
    if not text:
        return None
    m = _GRAD.search(text) or _GRAD_BRACKET.search(text)
    return 2000 + int(m.group(1)) if m else None


def batch_from_text(text: str | None) -> str | None:
    if not text:
        return None
    for batch, words in _BATCHES:
        if any(w in text for w in words):
            return batch
    return None


TAXONOMY = Path(__file__).resolve().parents[2] / "taxonomy" / "categories.yaml"


@cache
def _rules() -> list[tuple[str, str, re.Pattern]]:
    if not TAXONOMY.exists():  # 以库的形式安装时没有规则表；归类只在采集端进行
        return []
    doc = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    return [(r["category"], r["subcategory"], re.compile("|".join(r["any"]), re.I)) for r in doc["rules"]]


def categorize(title: str | None) -> tuple[str | None, str | None]:
    """按 taxonomy/categories.yaml 归类岗位标题；没有命中返回 (None, None)。"""
    if title:
        for category, subcategory, pattern in _rules():
            if pattern.search(title):
                return category, subcategory
    return None, None


_CITY_SPLIT = re.compile(r"[,，、;；/|]")
_CITY_LEVELS = re.compile(r"[-·—]")


def cities_from_text(text: str | None) -> list[str]:
    """"江苏省-连云港市,北京市" -> ["连云港", "北京"]：取最末一级，去掉"市"后缀，去重保序。"""
    if not text:
        return []
    out: list[str] = []
    for part in _CITY_SPLIT.split(text):
        name = _CITY_LEVELS.split(part.strip())[-1].strip()
        if len(name) > 2 and name.endswith("市"):
            name = name[:-1]
        if name and name not in out:
            out.append(name)
    return out
