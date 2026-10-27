"""`dedupe_auto`：人工条目已覆盖的批次，自动条目不能再重复出现。

实测背景（2026-10-26）：日历里 360 集团同时有两条「校招」——人工一条、自动一条，
214 组同键条目里有 11 组截止日互相矛盾。用户问「360 集团校招什么时候截止」
会拿到两个不同答案，这比少一条更糟。

规则不是「谁新用谁」，而是按可信度：
  - 人工条目来自官方公告原文；自动条目是从职位列表反推的，字段天然更弱；
  - 同 (集团, 批次, 届次) 已被人工覆盖 → 丢自动；
  - 自动条目没写届次、人工覆盖了同批次 → 也丢（否则「校招/None」和「校招/2027」并列）；
  - 届次不同的**都保留**：那可能是不同届的两个批次，合并会把两届混成一条。
"""

from jobradar.pipeline.calendar import dedupe_auto


def _row(origin, group, ptype, year, end=None, company=None):
    return {"origin": origin, "group_name": group, "company": company,
            "project_type": ptype, "grad_year": year, "apply_end": end}


def test_auto_yields_to_manual_same_batch_same_year():
    rows = [_row("manual", "甲", "校招", 2027, "2026-10-31"),
            _row("auto", "甲", "校招", 2027, None)]
    out = dedupe_auto(rows)
    assert [r["origin"] for r in out] == ["manual"]
    assert out[0]["apply_end"] == "2026-10-31"


def test_auto_without_year_yields_when_manual_covers_batch():
    rows = [_row("manual", "甲", "校招", 2027),
            _row("auto", "甲", "校招", None)]
    assert [r["origin"] for r in dedupe_auto(rows)] == ["manual"]


def test_different_years_are_both_kept():
    """2026 届和 2027 届是两个批次，不能因为同属「校招」就合并。"""
    rows = [_row("manual", "甲", "校招", 2026),
            _row("auto", "甲", "校招", 2027)]
    assert len(dedupe_auto(rows)) == 2


def test_different_project_types_are_both_kept():
    rows = [_row("manual", "甲", "校招", 2027),
            _row("auto", "甲", "实习", 2027)]
    assert len(dedupe_auto(rows)) == 2


def test_different_companies_are_untouched():
    rows = [_row("manual", "甲", "校招", 2027),
            _row("auto", "乙", "校招", 2027)]
    assert len(dedupe_auto(rows)) == 2


def test_auto_only_entries_survive():
    rows = [_row("auto", "甲", "校招", 2027), _row("auto", "甲", "校招", 2026)]
    assert len(dedupe_auto(rows)) == 2


def test_order_is_preserved():
    rows = [_row("manual", "乙", "校招", 2027), _row("manual", "甲", "校招", 2027),
            _row("auto", "甲", "校招", 2027)]
    out = dedupe_auto(rows)
    assert [r["group_name"] for r in out] == ["乙", "甲"]


# ---- 字段级互补：自动条目被丢弃前，先把人工条目空着的字段补上 ----
#
# 实测背景（2026-10-26）：蔚来/小鹏/华为的人工入口条目只有投递入口一项，
# cities / apply_end / grad_year 全空；同公司的自动条目从 429 条结构化职位里
# 带着完整城市与截止日。原实现把自动条目直接丢掉，产品里就成了「城市未知、无网申时间」——
# 数据在手却看不见。以下用例把「补什么、不补什么」钉死。


def _row_full(origin, group, ptype, year, **kw):
    base = {"origin": origin, "group_name": group, "company": None,
            "project_type": ptype, "grad_year": year, "apply_start": None, "apply_end": None,
            "cities": [], "tracks": []}
    base.update(kw)
    return base


def test_auto_fills_empty_fields_of_manual_entry():
    manual = _row_full("manual", "蔚来", "校招", None)
    auto = _row_full("auto", "蔚来", "校招", None, cities=["上海", "合肥"], apply_end="2026-11-30")
    out = dedupe_auto([manual, auto])
    assert len(out) == 1 and out[0]["origin"] == "manual"
    assert out[0]["cities"] == ["上海", "合肥"]
    assert out[0]["apply_end"] == "2026-11-30"


def test_manual_values_are_never_overwritten():
    manual = _row_full("manual", "甲", "秋招正式批", 2027, apply_end="2026-10-31", cities=["北京"])
    auto = _row_full("auto", "甲", "秋招正式批", 2027, apply_end="2026-12-31", cities=["上海"])
    out = dedupe_auto([manual, auto])
    assert out[0]["apply_end"] == "2026-10-31"   # 只补空值，不覆盖人工写的日期
    assert out[0]["cities"] == ["北京"]


def test_merge_also_fills_tracks():
    """届次不同会被规则分开（见下一条用例），所以「补届次」只能在同届次的噪声条目上发生；
    这里验证方向列表能被补进人工条目。"""
    manual = _row_full("manual", "乙", "校招", None)
    auto = _row_full("auto", "乙", "校招", None,
                     tracks=[{"direction": "技术类", "roles": []}])
    out = dedupe_auto([manual, auto])
    assert len(out) == 1
    assert out[0]["tracks"] == [{"direction": "技术类", "roles": []}]


def test_no_merge_when_years_differ():
    """届次不同时两条都保留，自动条目不能被「吸收」掉。"""
    manual = _row_full("manual", "丙", "校招", 2026)
    auto = _row_full("auto", "丙", "校招", 2027, cities=["深圳"])
    assert len(dedupe_auto([manual, auto])) == 2


def test_source_provenance_moves_with_the_field():
    """城市的证据来源必须跟着城市一起搬：否则日历里写「官网入口页」却带着职位表的城市，
    用户按来源去核实会看到入口页上根本没有这些信息。

    实测口径（2026-10-26 蔚来）：人工条目本来就写了来源（官网入口页），只是没写城市；
    城市来自飞书职位列表。这时**来源必须换成职位列表**，否则「城市=上海」挂在
    campus.nio.com 上，用户点进去看不到任何城市信息。
    """
    manual = _row_full("manual", "蔚来", "校招", None, source_type="official_site",
                       source_name="蔚来招聘官网", source_url="https://campus.nio.com/", jd_status="none",
                       observed_from=None, observed_to=None)
    auto = _row_full("auto", "蔚来", "校招", None, cities=["上海"], source_type="official_site",
                     source_name="招聘站职位列表", source_url="https://nio.jobs.feishu.cn/campus",
                     observed_from="2026-10-25", observed_to="2026-10-25", jd_status="linked")
    out = dedupe_auto([manual, auto])
    assert out[0]["source_name"] == "招聘站职位列表"
    assert out[0]["source_url"] == "https://nio.jobs.feishu.cn/campus"
    assert out[0]["observed_from"] == "2026-10-25"
    assert out[0]["jd_status"] == "linked"


def test_provenance_is_kept_when_no_data_field_was_borrowed():
    """只借了「空字段」里的证据字段、没借任何数据字段时，不能白白把来源改掉——
    人工写「9 月 1 日开放、截止 10 月 31 日」来自官网公告，来源就该还是官网公告。"""
    manual = _row_full("manual", "丁", "校招", 2027, apply_start="2026-09-01", apply_end="2026-10-31",
                       source_name="官方公告", source_url="https://example.com/notice", jd_status="none")
    auto = _row_full("auto", "丁", "校招", 2027, apply_start="2026-09-01", apply_end="2026-10-31",
                     source_name="职位列表", source_url="https://example.com/jobs", jd_status="linked")
    out = dedupe_auto([manual, auto])
    assert out[0]["source_name"] == "官方公告"
    assert out[0]["jd_status"] == "none"
