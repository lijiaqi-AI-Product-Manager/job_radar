"""从岗位标题等文本中提取校招字段。规则保守：拿不准就返回 None（CLAUDE.md：不要猜）。"""

import re

_GRAD = re.compile(
    r"(?<![\dA-Za-z])(?:20)?(2[4-9]|3[0-2])\s*(?:届|(?:秋季|春季)?(?:校招|校园招聘|秋招|春招|暑期实习|实习))"
)
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
    m = _GRAD.search(text)
    return 2000 + int(m.group(1)) if m else None


def batch_from_text(text: str | None) -> str | None:
    if not text:
        return None
    for batch, words in _BATCHES:
        if any(w in text for w in words):
            return batch
    return None
