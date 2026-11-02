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
