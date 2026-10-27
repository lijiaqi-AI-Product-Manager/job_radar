"""公司名归一化：判断「西门子 / 西门子中国」「通威 / 通威股份」是不是同一家。

只做字符串层面的确定性归一（去括号、去集团/股份/有限公司等后缀、去前后「中国」），
不做拼音/模糊匹配——宁可漏并，也不能把「华润」和「华润万家」并成一家。
"""
from __future__ import annotations

import re

SUFFIX = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团控股|集团|控股|股份|公司)$")
PAREN = re.compile(r"[（(][^)）]*[)）]")
NEWS = re.compile(r"(xwzx|mtgz|news|/about|/gywm|/zoujin|/jrwm|/gongsijianjie)", re.I)

# 去掉「中国」就变成别的意思/别的实体，不做剥离
KEEP_CN = {"中国黄金", "中国建筑", "中国中铁", "中国铁建", "中国交建", "中国电建",
           "中国能建", "中国中车", "中国船舶", "中国商飞", "中国移动", "中国电信",
           "中国联通", "中国石油", "中国石化", "中国海油", "中国人寿", "中国平安",
           "中国银行", "中国农业银行", "中国工商银行", "中国建设银行", "中国邮政"}

KNOWN_ATS = {"beisen", "beisen_legacy", "hotjob", "hotjob_legacy", "feishu_atsx",
             "tupu360", "workday", "dayee", "self_hosted"}


def core(name: str) -> str:
    n = PAREN.sub("", (name or "").strip()).replace(" ", "")
    changed = True
    while changed:
        changed = False
        m = SUFFIX.search(n)
        if m and len(n) - len(m.group(0)) >= 2:
            n = n[: m.start()]
            changed = True
    return n


def key(name: str) -> str:
    n = core(name)
    if n.startswith("中国") and len(n) > 2 and n not in KEEP_CN:
        n = n[len("中国"):]
    if n.endswith("中国") and len(n) > 2:
        n = n[: -len("中国")]
    return n


def score(row: dict) -> tuple:
    """合并时保留哪一行：认得的 ATS 入口 > 不像新闻/介绍页 > 岗位数 > 日历条目。"""
    url = row.get("careers_url") or ""
    return (row.get("ats") in KNOWN_ATS, not NEWS.search(url),
            row.get("roles") or 0, row.get("calendar_entries") or 0)
