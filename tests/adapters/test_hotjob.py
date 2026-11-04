import json
from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.hotjob import HotjobAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "hotjob"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


def run(**params):
    a = HotjobAdapter(source(**params), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_field_mapping_of_real_record():
    j = next(j for j in run() if j.source_job_id == "6aaa2c10b6fae46f67553282")
    assert j.company == "中联重科"
    assert j.title == "博士直通车（机器人和人工智能方向）"
    assert j.recruit_type == "campus"
    assert j.cities == ["长沙"]                     # workPlaceStr「长沙市」→ 去掉「市」
    assert j.degree_min == "博士及以上"
    assert j.department == "中央研究院" or j.department  # 事业部名
    assert j.url.startswith("https://wecruit.hotjob.cn/SU60a6449a2f9d2430fdc11a19/pb/posDetail.html?postId=")
    assert "具身智能" in (j.description or "")       # 详情接口的 workContent


def test_every_job_has_jd_text():
    jobs = run()
    assert len(jobs) == 12
    assert all((j.description or "").strip() or (j.requirements or "").strip() for j in jobs)


def test_detail_can_be_disabled_to_save_requests():
    jobs = run(fetch_detail=False)
    assert jobs and all(j.description is None for j in jobs)


def _cache(jobs, fetched_at="2026-11-01T00:00:00Z"):
    return {j.source_job_id: {"title": j.title, "publish_at": j.publish_at,
                             "recruit_type": j.recruit_type, "degree_min": j.degree_min,
                             "description": j.description, "requirements": j.requirements,
                             "fetched_at": fetched_at} for j in jobs}


def test_cached_text_keeps_actual_observation_and_avoids_detail_requests(monkeypatch):
    monkeypatch.setattr("jobradar.adapters.hotjob.now_ts", lambda: "2026-11-02T00:00:00Z", raising=False)
    original = run()
    adapter = HotjobAdapter(source(detail_cache_hours=168), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda _: None)
    adapter.cached_texts = _cache(original)
    calls = []
    adapter._detail = lambda post_id: calls.append(post_id) or {}
    jobs = list(adapter.fetch_all())
    assert calls == []
    assert len(jobs) == len(original)
    assert jobs[0].description == original[0].description
    assert jobs[0].text_observed_at == "2026-11-01T00:00:00Z"


@pytest.mark.parametrize("date", ["2026-10-01T00:00:00Z", "2027-01-01T00:00:00Z", "invalid"])
def test_expired_future_or_invalid_cache_requires_detail_request(monkeypatch, date):
    monkeypatch.setattr("jobradar.adapters.hotjob.now_ts", lambda: "2026-11-02T00:00:00Z", raising=False)
    original = run()
    adapter = HotjobAdapter(source(detail_cache_hours=168), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda _: None)
    adapter.cached_texts = _cache(original, date)
    calls = []
    request = adapter._detail
    adapter._detail = lambda post_id: calls.append(post_id) or request(post_id)
    jobs = list(adapter.fetch_all())
    assert len(calls) == len(original)
    assert all(j.text_observed_at is None for j in jobs)


def test_changed_title_invalidates_cached_text(monkeypatch):
    monkeypatch.setattr("jobradar.adapters.hotjob.now_ts", lambda: "2026-11-02T00:00:00Z", raising=False)
    original = run()
    adapter = HotjobAdapter(source(detail_cache_hours=168), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda _: None)
    adapter.cached_texts = _cache(original)
    adapter.cached_texts[original[0].source_job_id]["title"] = "旧的岗位标题"
    calls = []
    request = adapter._detail
    adapter._detail = lambda post_id: calls.append(post_id) or request(post_id)
    jobs = list(adapter.fetch_all())
    assert calls == [original[0].source_job_id]
    assert jobs[0].text_observed_at is None
    assert all(j.text_observed_at for j in jobs[1:])


@pytest.mark.parametrize("bad", [{}, {"data": None}, {"data": {"pageForm": {"pageData": "error"}}},
                                {"data": {"pageForm": {"pageData": [], "totalPage": 2}}}])
def test_incomplete_second_page_is_not_accepted_as_a_complete_source(bad):
    config = source(fetch_detail=False, max_pages=None)
    adapter = HotjobAdapter(config, httpx.Client(), sleep=lambda _: None)
    pages = iter([{"data": {"pageForm": {"pageData": [{"postId": "one", "postName": "工程师"}], "totalPage": 2}}}, bad])
    adapter._list = lambda *_: next(pages)
    with pytest.raises(RuntimeError):
        list(adapter.fetch_all())


def test_repeated_full_page_cannot_become_a_successful_partial_source():
    adapter = HotjobAdapter(source(fetch_detail=False, max_pages=None), httpx.Client(), sleep=lambda _: None)
    adapter._list = lambda *_: {"data": {"pageForm": {"pageData": [{"postId": "one", "postName": "工程师"}], "totalPage": 2}}}
    with pytest.raises(RuntimeError, match="repeated"):
        list(adapter.fetch_all())


def test_failed_detail_read_retains_old_body_and_its_time(monkeypatch):
    monkeypatch.setattr("jobradar.adapters.hotjob.now_ts", lambda: "2026-11-02T00:00:00Z")
    original = run()
    adapter = HotjobAdapter(source(detail_cache_hours=168), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda _: None)
    adapter.cached_texts = _cache(original, "2026-10-01T00:00:00Z")
    def fail(_):
        raise RuntimeError("unavailable detail")
    adapter._detail = fail
    jobs = list(adapter.fetch_all())
    assert jobs[0].description == original[0].description
    assert jobs[0].text_observed_at == "2026-10-01T00:00:00Z"


def test_verified_htsc_requirements_supply_explicit_fields_only_when_enabled():
    evidence = json.loads((FX / "htsc-requirement-evidence.json").read_text(encoding="utf-8"))
    raw = {"list": {"postId": "6acf28c115a82a89c323b05c", "postName": evidence["title"]},
           "detail": {"serviceCondition": evidence["requirement_excerpt"]}, "recruit_type": "campus"}
    config = source(detail_fields=True, tenant="SU5d4bd89a9b0d7889b8422dbe")
    config.company = "华泰证券"
    enabled = HotjobAdapter(config, httpx.Client())
    job = enabled.normalize(raw)
    assert job.grad_year == 2027 and job.degree_min == "硕士"
    disabled = HotjobAdapter(source(), httpx.Client())
    assert disabled.normalize(raw).grad_year is None
    raw["detail"]["serviceCondition"] += "2026届毕业生亦可。"
    assert enabled.normalize(raw).grad_year is None


@pytest.mark.parametrize('evidence', json.loads((FX/'verified-requirements.json').read_text(encoding='utf-8')),
                         ids=lambda r:r['source_id'])
def test_current_verified_tenant_requirement_evidence(evidence):
    with httpx.Client() as client:
        enabled=HotjobAdapter(source(detail_fields=True),client)
        assert enabled.normalize(evidence['raw']).grad_year==evidence['expected_grad_year']
        disabled=HotjobAdapter(source(detail_fields=False),client)
        assert disabled.normalize(evidence['raw']).grad_year is None


def test_followup_pages_use_actual_server_page_size():
    evidence = json.loads((FX / 'pagination-evidence.json').read_text(encoding='utf-8'))
    requested = []
    def respond(request):
        page = int(request.url.params['currentPage'])
        size = int(request.url.params['pageSize'])
        requested.append((page, size))
        actual_size = evidence['first_response']['pageSize'] if page == 1 else size
        start = 0 if page == 1 else (page - 1) * size
        rows = [{'postId': str(i), 'postName': '工程师'} for i in range(start + 1, min(start + actual_size, 19) + 1)]
        form = {'totalPage': (19 + actual_size - 1) // actual_size, 'pageSize': actual_size,
                'currentPage': page, 'dataCount': 19, 'pageData': rows}
        return httpx.Response(200, json={'data': {'pageForm': form}})
    config = source(fetch_detail=False, page_size=50, max_pages=None).model_copy(update={'recruit_types': ['campus']})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        jobs = list(HotjobAdapter(config, client, sleep=lambda _: None).fetch_all())
    assert len(jobs) == 19
    assert requested == [(1, 50), (2, 12)]


def test_explicit_empty_first_page_is_valid_but_cannot_hide_incomplete_page():
    config = source(fetch_detail=False).model_copy(update={'recruit_types': ['campus']})
    adapter = HotjobAdapter(config, httpx.Client(), sleep=lambda _: None)
    adapter._list = lambda *_: {'data': {'pageForm': {'totalPage': 1, 'dataCount': 0, 'pageData': []}}}
    assert list(adapter.fetch_all()) == []
    adapter._list = lambda *_: {'data': {'pageForm': {'totalPage': 1, 'dataCount': 19, 'pageData': []}}}
    with pytest.raises(RuntimeError, match='incomplete'):
        list(adapter.fetch_all())


def test_public_tenant_identifiers_use_canonical_hex_case():
    with httpx.Client() as client:
        adapter = HotjobAdapter(source(tenant='SU6149FF530DCAD47003D01511'), client)
        assert adapter.tenant == 'SU6149ff530dcad47003d01511'


def test_missing_platform_degree_does_not_invalidate_derived_cache(monkeypatch):
    monkeypatch.setattr('jobradar.adapters.hotjob.now_ts', lambda: '2026-11-02T00:00:00Z')
    original = run()[0]
    with httpx.Client() as client:
        adapter = HotjobAdapter(source(detail_cache_hours=168), client)
        adapter.cached_texts = _cache([original])
        adapter.cached_texts[original.source_job_id]['degree_min'] = '本科'
        item = {'postId': original.source_job_id, 'postName': original.title,
                'publishDate': original.publish_at, 'educationStr': None}
        cached = adapter._cached_detail(item, original.recruit_type)
        assert cached is not None and cached[1] == '2026-11-01T00:00:00Z'
        item['educationStr'] = '硕士'
        assert adapter._cached_detail(item, original.recruit_type) is None
