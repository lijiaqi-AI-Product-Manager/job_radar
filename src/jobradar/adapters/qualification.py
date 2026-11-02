"""已核验要求字段中的单届证据；只由显式启用的适配器调用。"""

import re
from html import unescape

_COHORT = re.compile(r"(?<!\d)(20\d{2})\s*(?:届|年应届毕业生)")
_EARLIER_MEMBER = re.compile(r"(?:20\d{2}|\d{2})\s*(?:[、,，/\-—~～]|或|至|到|和|及)\s*$")
_OPEN_RANGE = re.compile(r"\s*(?:[（(]\s*含\s*[）)]\s*)?(?:及|或|和)?\s*(?:以前|之前|以后|之后|以上|以下|往届)")
_EXCLUSION = re.compile(r"(?:不接受|不招收|不含|不包括|非|除)\s*$")


def requirement_grad_year(requirement: str | None) -> int | None:
    """多届、开放范围或排除条款不能表示一个grad_year。

    只读已逐源确认用途的任职要求字段；不从通用JD、当前年份或观测时间推导。
    结构化范围沿用公开数据门禁的2023—2032；范围外原文保留，字段未知。
    “2026、2027届”中2026没有紧邻“届”，仍属于同一申请范围。
    """
    if not isinstance(requirement, str):
        return None
    text = unescape(re.sub(r"<[^>]+>", " ", requirement))
    years = set()
    for match in _COHORT.finditer(text):
        before = text[max(0, match.start()-40):match.start()]
        after = text[match.end():]
        if _EARLIER_MEMBER.search(before) or _EXCLUSION.search(before) or _OPEN_RANGE.match(after):
            return None
        years.add(int(match[1]))
    if len(years) != 1:
        return None
    year = next(iter(years))
    return year if 2023 <= year <= 2032 else None
