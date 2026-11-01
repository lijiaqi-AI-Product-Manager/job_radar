"""证据字典的名字归一匹配：`work/build_calendar.py` 里的 _norm_company_name / build_evidence_index。

为什么单独锁这一条：数据层里的公司名是抓下来的原始名（「潍柴动力股份有限公司」），
targets 里是简称（「潍柴动力」），日历条目用的又是第三个名字。原来只做精确匹配，
结果结构化证据（城市/截止日/届次）对相当一部分公司根本没生效——
文件里有证据、日历里却是空的，这种「数据到了但没到产品里」的错最难靠肉眼发现。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work"))

from build_calendar import (  # noqa: E402
    _norm_company_name,
    build_evidence_index,
    load_ats_evidence,
    lookup_evidence,
    merge_evidence,
)


def test_norm_strips_legal_suffix_and_parens():
    assert _norm_company_name("潍柴动力股份有限公司") == "潍柴动力"
    assert _norm_company_name("三一集团有限公司") == "三一集团"
    assert _norm_company_name("宝洁（中国）有限公司") == "宝洁"
    assert _norm_company_name(" 中国 平安 ") == "中国平安"
    # 只有后缀本身、没有实义名字时不剥（否则会剥成空串，索引里出现空键）
    assert _norm_company_name("公司") == "公司"


def test_lookup_hits_full_name_and_short_name():
    idx = build_evidence_index({
        "潍柴动力股份有限公司": {"company": "潍柴动力股份有限公司", "cities": ["潍坊"]},
        "北森": {"company": "北森", "cities": ["北京"]},
    })
    assert lookup_evidence(idx, "潍柴动力股份有限公司")["cities"] == ["潍坊"]
    assert lookup_evidence(idx, "潍柴动力")["cities"] == ["潍坊"]
    assert lookup_evidence(idx, "北森")["cities"] == ["北京"]


def test_lookup_never_substring_matches():
    """不做子串匹配：「中国银行」不能拿到「中国银行保险」的证据——比漏匹配更糟。"""
    idx = build_evidence_index({"中国银行保险": {"company": "中国银行保险", "cities": ["北京"]}})
    assert lookup_evidence(idx, "中国银行") is None
    assert lookup_evidence(idx, "中国") is None


def test_school_display_expiry_is_not_application_deadline():
    # 广工/郑大公告：发布时间与过期时间是站内展示元数据。
    notice = {"title": "2027届秋招", "publish": "2026-09-01",
              "expire": "2026-11-01", "site_short": "广工就业网",
              "url": "https://career.gdut.edu.cn/campus/view/id/1020881",
              "text": "欢迎投递简历，招满即止。"}
    merged = merge_evidence("汉得信息", {}, None, [notice], None)
    batch = merged["batches"]["秋招正式批"]
    assert batch["ends"] == []
    assert "window" not in merged["ev"]


def test_school_expired_label_does_not_override_explicit_application_window():
    notice = {"title": "2027届秋招", "publish": "2026-09-01",
              "expire": "2026-11-01", "expired_flag": True,
              "text": "网申时间：2026年10月10日至2026年12月9日。"}
    merged = merge_evidence("齐鲁制药", {}, None, [notice], None)
    batch = merged["batches"]["秋招正式批"]
    assert batch["starts"] == ["2026-10-10"]
    assert batch["ends"] == ["2026-12-09"]


def test_lookup_missing_returns_none():
    assert lookup_evidence({}, "任意公司") is None
    assert lookup_evidence({"甲": {"company": "甲"}}, "") is None
    assert lookup_evidence({"甲": {"company": "甲"}}, "乙") is None


def test_load_ats_evidence_tolerates_missing_file(tmp_path):
    assert load_ats_evidence(tmp_path / "nope.jsonl") == {}


def test_load_ats_evidence_skips_rows_without_company(tmp_path):
    p = tmp_path / "ev.jsonl"
    p.write_text('{"company": "甲", "cities": ["北京"]}\n{"cities": ["上海"]}\n', encoding="utf-8")
    ev = load_ats_evidence(p)
    assert list(ev) == ["甲"]
