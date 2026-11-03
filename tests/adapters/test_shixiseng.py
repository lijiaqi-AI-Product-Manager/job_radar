from pathlib import Path

import httpx
import yaml

from jobradar.adapters.recording import ReplayTransport
from jobradar.adapters.shixiseng import ShixisengAdapter, clean_title, same_company
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "shixiseng_shixiseng-kuaishou"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = ShixisengAdapter(
        source(**params), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None
    )
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    j = next(j for j in run() if j.source_job_id == "inn_93nlott6b9fb")
    assert j.company == "快手"
    assert j.title == "影视综漫垂类运营实习生-【主站】"   # 图标码点 &#xe05d 已清掉
    assert j.recruit_type == "intern"
    assert j.cities == ["北京"]
    assert str(j.apply_end) == "2026-12-30"             # 详情页 endtime
    assert j.url == "https://www.shixiseng.com/intern/inn_93nlott6b9fb"
    assert j.degree_min in (None, "本科")
    assert len(j.description or "") > 200               # 详情页 info 转纯文本


def test_all_jobs_have_jd_text():
    jobs = run()
    assert len(jobs) == 20
    assert all((j.description or "").strip() for j in jobs)


def test_public_detail_preserves_pay_and_internship_schedule():
    j = next(j for j in run() if j.source_job_id == "inn_93nlott6b9fb")
    assert "薪资：180-200/天" in j.requirements
    assert "每周出勤：5天/周" in j.requirements
    assert "实习时长：4个月" in j.requirements
    assert "负责影剧综漫" in j.description


def test_unreadable_pay_and_missing_detail_do_not_create_terms():
    a = ShixisengAdapter(source(), httpx.Client(), sleep=lambda s: None)
    raw = {"list": {"uuid": "sample", "name": "实习生", "cname": "快手", "minsal": "180", "maxsal": "200"},
           "detail": {"minsal": "&#xe2f2", "maxsal": "200", "day": 0, "month": None}}
    j = a.normalize(raw)
    assert j.requirements is None
    assert a.normalize({"list": raw["list"]}).requirements is None


def test_invalid_ranges_never_become_promised_pay_or_schedule():
    a = ShixisengAdapter(source(), httpx.Client(), sleep=lambda s: None)
    raw = {"list": {"uuid": "sample", "name": "实习生", "cname": "快手"},
           "detail": {"minsal": "300", "maxsal": "100", "day": 8, "month": -1}}
    assert a.normalize(raw).requirements is None


def test_detail_can_be_disabled_to_save_requests():
    jobs = run(fetch_detail=False)
    assert jobs and all(j.description is None for j in jobs)
    assert all(j.title for j in jobs)                   # 列表页也带标题


def test_titles_have_no_icon_codepoints():
    assert all("&#x" not in j.title for j in run(fetch_detail=False))
    assert clean_title("运营实习&#xe05d-【主站】") == "运营实习-【主站】"


def test_ownership_gate_rejects_lookalike_companies():
    # 关键词是模糊匹配：查「宁德时代」会返回「时代博川」，这道闸门不能删
    assert same_company("快手", "快手")
    assert same_company("快手科技", "北京快手科技有限公司")
    assert same_company("快手", "快手科技")                     # 母品牌前缀
    assert same_company("华为", "华为云计算技术有限公司")        # 母品牌前缀，算同一集团
    assert not same_company("小米", "达州小米汽车有限公司")      # 2 字名不做任意子串匹配
    assert not same_company("宁德时代", "时代博川")
    assert not same_company(None, "快手")


def test_skips_jobs_of_other_companies():
    """把目标公司改成别家，同一个 fixtures 里应当一条都留不下。"""
    a = ShixisengAdapter(
        source(keyword="快手"), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None
    )
    a.source.company = "宁德时代"
    assert list(a.fetch_all()) == []
