"""高校就业网（campus）适配器测试。

fixtures 由 `scripts/record_fixtures.py campus-hebut-jiangsushengguoxin --multi-source --max-pages 1`
录制（2026-10-30）：河北工业大学就业网「招聘信息」列表页 + 1 个详情页。

覆盖三件事：
1. 三种皮肤（南开/天工大 A、河北工大 B、天津科技大 C）都能解析出条目；
2. 归属闸门：只有列表里的公司名归一后与 params.match 完全相等才入库，改个名字就 0 条；
3. 详情页字段（工作地域/学历/发布时间/职位描述）落进 Job。
"""

from pathlib import Path

import httpx
import yaml

from jobradar.adapters.campus import (
    CampusAdapter,
    company_core,
    parse_detail_page,
    parse_list_page,
    same_company,
)
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "campus_campus-hebut-jiangsushengguoxin"

# 三种皮肤的最小样本（真实站点的结构，删掉了无关包裹）
THEME_A = """
<li><div class="date"><span class="day">16</span><span class="year">2026.10</span></div>
<div class="title1"><a href="/correcruit/content/id/1.html">算法工程师</a></div>
<div class="company"><a href="/company/index/id/2.html">【华为技术有限公司】</a>深圳市 / 本科 / 20000-30000元</div></li>
"""
THEME_B = """
<ul class="zpxx clearfix"><li><div class="l">
<a class="up" href="/correcruit/content/id/82142.html" target="_blank">河北金租2027届校园招聘简章</a>
<a class="down" href="/company/index/id/20068.html" target="_blank">河北省金融租赁有限公司</a>
</div><div class="r">2026-10-30</div></li></ul>
"""
THEME_C = """
<ul class="zhaopin_ul"><li><div class="zw_title clearfix"><div class="zw_titleleft clearfix">
<a class="lizw" href="/correcruit/content/id/47063.html" target="_blank">电仪技术员</a>
<a class="ligs" href="/company/index/id/10844.html" target="_blank">山西强伟纸业有限公司</a></div>
<p>2026-10-30</p></div>
<div class="zw_cate">山西省 / 工程技术人员 / 本科 / 6000-8000元</div></li></ul>
"""


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def fetch(**params):
    src = source(**params)
    client = httpx.Client(transport=ReplayTransport(FX))
    return src, list(CampusAdapter(src, client, sleep=lambda s: None).fetch_all())


def test_three_themes_parse():
    a = parse_list_page(THEME_A, "https://career.nankai.edu.cn")
    b = parse_list_page(THEME_B, "https://career.hebut.edu.cn")
    c = parse_list_page(THEME_C, "https://jy.tust.edu.cn")
    assert [x["company"] for x in a] == ["华为技术有限公司"]
    assert a[0]["title"] == "算法工程师" and a[0]["date"] == "2026-10-16"
    assert a[0]["cities"] == ["深圳市"] and a[0]["degree"] == "本科"
    assert [x["company"] for x in b] == ["河北省金融租赁有限公司"]
    assert b[0]["date"] == "2026-10-30"
    assert [x["company"] for x in c] == ["山西强伟纸业有限公司"]
    assert c[0]["cities"] == ["山西省"] and c[0]["salary"] == "6000-8000元"


def test_company_match_is_exact_after_normalising_suffix():
    assert company_core("江苏省国信集团有限公司") == "江苏省国信"
    assert same_company("江苏省国信集团有限公司", "江苏省国信")
    assert same_company("蓝月亮（中国）有限公司", "蓝月亮（中国）有限公司")
    # 刻意不做模糊：地名/同名不同业必须挡住
    assert not same_company("迪卡侬（上海）体育用品有限公司南开大悦城分公司", "大悦城")
    assert not same_company("东莞市步步高实验学校", "步步高")


def test_fixture_yields_jobs_with_fields():
    src, jobs = fetch()
    assert jobs, "回放后一条岗位都没有"
    job = jobs[0]
    assert job.company == src.company
    assert job.source_id == src.id
    assert job.recruit_type == "campus"
    assert job.title.strip() and job.url.startswith("https://")
    assert job.publish_at and job.publish_at.startswith("20")
    assert (job.description or "").strip(), "详情页的职位描述没落库"


def test_jd_text_is_stored():
    _, jobs = fetch()
    with_jd = [j for j in jobs if (j.description or "").strip()]
    assert len(with_jd) == len(jobs)


def test_attribution_gate_drops_other_companies():
    """把 match 改成一个不在列表里的名字，必须一条都不剩。"""
    _, jobs = fetch(match=["宁德时代新能源科技股份有限公司"])
    assert jobs == []


def test_detail_parser_reads_labelled_fields():
    html = (
        "<html><body><p>工作地域：河北省</p><p>职位类别：工程技术人员</p>"
        "<p>学历要求：硕士</p><p>招聘人数：2人</p><p>发布时间：2026-10-08</p>"
        "<p>职位投递网址链接：https://example.com/campus</p>"
        "<p>职位描述：岗位职责<br/>1. 做事情</p></body></html>"
    )
    d = parse_detail_page(html)
    assert d["city"] == "河北省"
    assert d["degree"] == "硕士"
    assert d["publish"] == "2026-10-08"
    assert d["apply_url"] == "https://example.com/campus"
    assert "做事情" in (d["description"] or "")
