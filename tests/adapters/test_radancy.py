"""Radancy 适配器契约测试。fixtures 由 scripts/record_fixtures.py radancy-sanofi 录制
（2026-10-26，max_pages=1, page_size=15）。

这组测试守的是**三种形态差异**：卡片是 `<a data-job-id><h2>` 而不是 `<a class="job-link"><h3>`，
地点是中文而不是英文，正文在 `section7-details` 而不是 `anchor-job-description`。
任何一处退回单一形态，这里就会红。"""

import re
from pathlib import Path

import httpx
import yaml

from jobradar.adapters.radancy import (
    RadancyAdapter,
    _cities,
    _clean_location,
    _en_date,
    recruit_type_of,
)
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "radancy"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = RadancyAdapter(source(**params), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_bare_anchor_cards_are_parsed():
    """赛诺菲的卡片是裸 `<a data-job-id>`，没有 job-link class。"""
    jobs = run(max_pages=1)
    assert len(jobs) == 15


def test_field_mapping_of_real_record():
    """用第一条卡片断言字段映射。

    岗位列表会随上下架变化（录 fixtures 时列表首位是另一条），所以这里按「第一条」取、
    断言**结构**而不是具体岗位名；具体值的断言放在 _cities/_en_date 的单元测试里。
    """
    j = run(max_pages=1)[0]
    assert j.company == "赛诺菲"
    assert j.source_job_id.isdigit()
    assert j.cities and all(c not in ("中国", "全国") for c in j.cities)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", j.publish_at)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", j.apply_end)
    assert j.recruit_type in ("social", "intern")
    assert j.description and len(j.description) > 50
    assert j.url.startswith("https://jobs.sanofi.cn/")
    assert j.source_job_id in j.url


def test_jd_and_dates_are_complete():
    """这是全项目字段最全的源：城市/发布日期/截止日/JD 四项都该是满的。

    fixtures 只留了 3 个详情响应（`--keep-details 3`），所以「日期/JD」只在**抓到详情**的
    那几条上断言；「城市」来自列表页，15 条全有，可以整体断言。
    """
    jobs = run(max_pages=1)
    assert all(j.cities for j in jobs)
    detailed = [j for j in jobs if j.description]
    assert len(detailed) == 3
    assert all(j.publish_at for j in detailed)
    assert all(j.apply_end for j in detailed)


def test_location_prefix_is_stripped():
    """`<strong>地点: </strong>北京, 中国` 里的「地点: 」要去掉，否则会被当成地名。"""
    assert _clean_location("地点: 北京, 中国") == "北京, 中国"
    assert _clean_location("北京, 中国") == "北京, 中国"
    assert _clean_location(None) is None


def test_chinese_location_parses_to_cities():
    """`city_from_english("北京")` 返回 None（只做英→中），中文必须走 cities_from_text。"""
    assert _cities("北京, 中国") == ["北京"]
    assert _cities("上海, 中国") == ["上海"]
    # 带「市」的一级优先（"上海市-闵行区" → 上海市 → 上海），和 cities_from_text 的既有规则一致
    assert _cities("上海市-闵行区, 中国") == ["上海"]
    # 英文串走另一条路，且不能被 cities_from_text 的中文规则污染
    assert _cities("Shanghai, Shanghai Municipality, China Mainland") == ["上海"]


def test_country_names_are_not_cities():
    """不过滤时 15 条岗位全带「中国」。"""
    assert "中国" not in _cities("北京, 中国")
    assert "印度" not in _cities("海得拉巴, 印度")
    assert _cities("全国") == []


def test_en_date():
    assert _en_date("<b>发布于 &nbsp;</b> Oct. 26, 2026") == "2026-10-26"
    assert _en_date("<b>申请截止于 &nbsp;</b> Nov. 30, 2026") == "2026-11-30"
    assert _en_date("<b>发布于</b> 2026-10-26") == "2026-10-26"
    assert _en_date("Posted 3 days ago") is None    # 相对文案不猜
    assert _en_date(None) is None


def test_recruit_type_of():
    assert recruit_type_of("DBU-Commercial Intern-天津", "Apprentice/Intern (Fixed Term)") == "intern"
    assert recruit_type_of("Summer Internship 2027") == "intern"
    assert recruit_type_of("Graduate Program 2027") == "campus"
    assert recruit_type_of("内部审计经理") == "social"      # 「内部」不是「实习」
    assert recruit_type_of("实习生-数据分析") == "intern"
