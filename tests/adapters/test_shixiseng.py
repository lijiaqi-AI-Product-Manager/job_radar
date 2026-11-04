import json
from pathlib import Path

import httpx
import pytest
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


def test_foreign_company_rows_are_skipped_before_detail_requests():
    adapter = ShixisengAdapter(source(), httpx.Client(), sleep=lambda _: None)
    adapter._list = lambda _: ([{'uuid': 'foreign', 'name': '实习生', 'cname': '宁德时代'},
                               {'uuid': 'matched', 'name': '实习生', 'cname': '快手'}], 2)
    requests = []
    adapter._detail = lambda uid: requests.append(uid) or {'cname': '快手', 'info': '工作职责'}
    assert len(list(adapter.fetch_all())) == 1
    assert requests == ['matched']


def _text_cache(jobs, stamp='2026-11-03T00:00:00Z'):
    return {j.source_job_id: {'title': j.title, 'degree_min': j.degree_min,
        'cities': json.dumps(j.cities, ensure_ascii=False), 'apply_end': j.apply_end,
        'description': j.description, 'requirements': j.requirements, 'fetched_at': stamp} for j in jobs}


def test_recent_verified_text_is_reused_without_claiming_a_new_observation(monkeypatch):
    monkeypatch.setattr('jobradar.adapters.shixiseng.now_ts', lambda: '2026-11-04T00:00:00Z', raising=False)
    original = run()
    adapter = ShixisengAdapter(source(detail_cache_hours=48), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda _: None)
    adapter.cached_texts = _text_cache(original)
    requests = []
    adapter._detail = lambda uid: requests.append(uid) or {}
    jobs = list(adapter.fetch_all())
    assert requests == []
    assert len(jobs) == len(original)
    assert all(j.text_observed_at == '2026-11-03T00:00:00Z' for j in jobs)
    assert [(j.description, j.requirements) for j in jobs] == [(j.description, j.requirements) for j in original]


@pytest.mark.parametrize('stamp', ['2026-10-01T00:00:00Z', '2027-01-01T00:00:00Z'])
def test_expired_or_future_text_requires_detail_read(monkeypatch, stamp):
    monkeypatch.setattr('jobradar.adapters.shixiseng.now_ts', lambda: '2026-11-04T00:00:00Z', raising=False)
    original = run()
    adapter = ShixisengAdapter(source(detail_cache_hours=48), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda _: None)
    adapter.cached_texts = _text_cache(original, stamp)
    requests = []
    detail = adapter._detail
    adapter._detail = lambda uid: requests.append(uid) or detail(uid)
    jobs = list(adapter.fetch_all())
    assert len(requests) == len(original)
    assert all(j.text_observed_at is None for j in jobs)


def test_parent_brand_does_not_prove_a_specific_subsidiary_owns_the_job():
    from jobradar.adapters.base import SkipRecord
    adapter = ShixisengAdapter(source(), httpx.Client())
    adapter.source.company = '网易有道'
    with pytest.raises(SkipRecord):
        adapter.normalize({'list': {'uuid': 'example', 'name': '实习生', 'cname': '网易'}})


@pytest.mark.parametrize('tail', [([], 40), ([{'uuid': str(i), 'name': '实习生', 'cname': '快手'} for i in range(20)], 40)])
def test_empty_or_repeated_second_page_is_never_a_complete_source(tail):
    adapter = ShixisengAdapter(source(fetch_detail=False, max_pages=None),
                              httpx.Client(), sleep=lambda _: None)
    pages = iter([([{'uuid': str(i), 'name': '实习生', 'cname': '快手'} for i in range(20)], 40), tail])
    adapter._list = lambda _: next(pages)
    with pytest.raises(RuntimeError):
        list(adapter.fetch_all())


def test_changed_city_invalidates_cached_text(monkeypatch):
    monkeypatch.setattr('jobradar.adapters.shixiseng.now_ts', lambda: '2026-11-04T00:00:00Z')
    original = run()
    adapter = ShixisengAdapter(source(detail_cache_hours=48), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda _: None)
    adapter.cached_texts = _text_cache(original)
    adapter.cached_texts[original[0].source_job_id]['cities'] = '["广州"]'
    calls = []
    detail = adapter._detail
    adapter._detail = lambda uid: calls.append(uid) or detail(uid)
    jobs = list(adapter.fetch_all())
    assert calls == [original[0].source_job_id]
    assert jobs[0].text_observed_at is None
    assert all(j.text_observed_at for j in jobs[1:])


def test_detail_budget_failure_is_not_swallowed():
    from jobradar.adapters.base import CrawlBudgetExceeded
    adapter = ShixisengAdapter(source(), httpx.Client(), sleep=lambda _: None)
    adapter._list = lambda _: ([{'uuid': 'one', 'name': '实习生', 'cname': '快手'}], 1)
    def interrupted(_):
        raise CrawlBudgetExceeded('crawl budget exceeded')
    adapter._detail = interrupted
    with pytest.raises(CrawlBudgetExceeded):
        list(adapter.fetch_all())


def test_listing_completes_before_details_and_overlapping_rows_are_deduplicated():
    adapter = ShixisengAdapter(source(max_pages=None), httpx.Client(), sleep=lambda _: None)
    order = []
    def listing(page):
        order.append(('list', page))
        start = 0 if page == 1 else 19
        return ([{'uuid': str(i), 'name': '实习生', 'cname': '快手'} for i in range(start, start + 20)], 40)
    adapter._list = listing
    adapter._detail = lambda uid: order.append(('detail', uid)) or {'cname': '快手', 'info': '真实工作职责'}
    jobs = list(adapter.fetch_all())
    assert len(jobs) == 39
    assert order[:2] == [('list', 1), ('list', 2)]
    assert len([item for item in order if item[0] == 'detail']) == 39
