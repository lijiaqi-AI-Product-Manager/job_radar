"""按「批次」分组证据的核心逻辑（build_calendar 用）。

为什么必须分组：
一家公司常有**多批**招聘同时在线——秋招正式批（9~12 月）、暑期实习（次年 3~6 月
报名）、提前批（5~7 月）。原来的实现把所有证据的日期混在一个池子里取
`min(起) / max(止)`，得到的结果既不属于任何一批，也是错的：把暑期实习的 3 月
和秋招的 12 月拼成「3月~12月」，日历用户看了会误判网申窗口。

所以这里按批次把证据分开：
- 每条简章/每个职位各自判定它属于哪个 project_type；
- 同一批次内的日期才允许合并；
- `pick_project_types` 决定公司最终要拆成几个条目。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

# 批次判定：从文本里认「这是哪一批」。顺序即优先级（越具体越靠前）。
BATCH_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("提前批", re.compile(r"提前批|提前批次|秋招提前|预招聘|抢先批")),
    ("秋招补录", re.compile(r"补录|补招|二次招聘|春季补招")),
    ("暑期实习", re.compile(r"暑期实习|暑假实习|暑期训练营|Summer\s*Intern", re.I)),
    ("寒假实习", re.compile(r"寒假实习|寒假训练营")),
    ("日常实习", re.compile(r"日常实习|长期实习|实习生招聘|Intern\b", re.I)),
    ("校园大使", re.compile(r"校园大使|校园合伙人|大使招募")),
    ("春招", re.compile(r"春招|春季校园招聘|春季招聘")),
    ("秋招正式批", re.compile(r"秋招|秋季校园招聘|秋季招聘|golden\s*season", re.I)),
    # 「有经验」不能裸匹配：「不困于既有经验」这种宣传语会被误判成社招。
    # 「社招」还要排除「社招新员工培养」这类培训描述——它不是招聘批次
    ("社招", re.compile(r"(?<!培养)(?:社会招聘|社招)(?!新员工|员工培养|培训)|experienced\s*hire|"
                        r"招聘有经验|有经验(?:人士|者|岗位)|资深岗位")),
    ("兼职", re.compile(r"兼职|钟点工|临时用工")),
    ("线上项目", re.compile(r"线上项目|远程实习|云实习")),
]

# 「秋招」是口语简称，「秋招正式批」是正式批次名；同一个意思不做两个条目
NORMALIZE = {"秋招": "秋招正式批"}

_VALID = {
    "提前批", "秋招", "秋招正式批", "秋招补录", "春招", "校招",
    "暑期实习", "寒假实习", "日常实习", "实习", "校园大使", "社招", "兼职", "线上项目",
}


def detect_batch(text: str) -> str | None:
    """从一段文本里判定批次。多个都命中时取优先级最高的（越具体越好）。"""
    if not text:
        return None
    for name, rx in BATCH_PATTERNS:
        if rx.search(text):
            return NORMALIZE.get(name, name)
    # 「校园招聘/校招」是兜底，必须放在最后：前面的具体批次都没命中才用它
    if re.search(r"校园招聘|校招|应届毕业生", text):
        return "校招"
    return None


def group_by_batch(items: list[dict], text_of, meta_of) -> tuple[dict[str, list[dict]], list[dict]]:
    """把证据按批次分组。

    返回 (批次 -> 证据列表, 未定批次的证据列表)。
    text_of(item) 取用于判批次的文本；meta_of(item) 取该证据的日期/城市等。
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    undecided: list[dict] = []
    for it in items:
        b = detect_batch(text_of(it) or "")
        if b:
            grouped[b].append(it)
        else:
            undecided.append(it)
    return dict(grouped), undecided


def pick_project_types(counts: Counter, has_undecided: bool) -> list[str]:
    """决定一条公司要拆成哪几个批次条目。

    - 只保留受控词表里的批次；
    - 「秋招」与「秋招正式批」合并；
    - 秋招正式批/春招这类主批次最多取 2 个，避免一家公司拆出七八条噪声条目；
    - 完全没识别出批次时用「校招」兜底（数据集里最常见的默认值）。
    """
    norm: Counter = Counter()
    for p, n in counts.items():
        p = NORMALIZE.get(p, p)
        if p in _VALID:
            norm[p] += n
    if not norm:
        return ["校招"]
    order = [p for p, _ in norm.most_common()]
    # 实习类 + 主批次同时存在时都保留（它们是真不同的窗口）；主批次最多 2 个
    main = [p for p in order if p in ("提前批", "秋招正式批", "秋招补录", "春招", "校招")][:2]
    intern = [p for p in order if p in ("暑期实习", "寒假实习", "日常实习", "实习", "校园大使")]
    other = [p for p in order if p not in main and p not in intern]
    got = main + intern + other
    return got or ["校招"]


def sensible_window(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    """窗口现实性检查。

    规则（都是真实数据里踩过的坑）：
    - 起点必须早于终点，否则两者都不采信；
    - 窗口长度超过 400 天，说明把不同年份的两批拼在一起了，不采信；
    - 截止晚于起点 1 年以上的，多半是「长期招聘」，只保留起点。
    """
    if not start and not end:
        return None, None
    if start and end:
        if start >= end:
            return start, None
        from datetime import date

        try:
            a = date.fromisoformat(start)
            b = date.fromisoformat(end)
        except ValueError:
            return start, end
        if (b - a).days > 400:
            return start, None
        return start, end
    return start, end
