"""逐源真实要求段与项目配置共同验收，不能只证明解析函数本身正确。"""

import json
from pathlib import Path

import httpx
import pytest

from jobradar.adapters.beisen import BeisenAdapter
from jobradar.adapters.hotjob import HotjobAdapter
from jobradar.adapters.qualification import requirement_grad_year
from jobradar.sources import load_sources

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = [record for adapter in ("beisen", "hotjob")
            for path in sorted((ROOT / "tests/fixtures" / adapter).glob("verified-requirements-r7-*.json"))
            for record in json.loads(path.read_text(encoding="utf-8"))]
CONFIGS = {source.id: source for source in load_sources(ROOT / "sources")}


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda record: record["source_id"])
def test_current_source_configuration_reads_verified_cohort(record):
    source = CONFIGS[record["source_id"]]
    with httpx.Client() as client:
        adapter = BeisenAdapter if source.adapter == "beisen" else HotjobAdapter
        job = adapter(source, client).normalize(record["raw"])
    assert job.grad_year == record["expected_grad_year"]


@pytest.mark.parametrize("year,expected", [(2017, None), (2022, None), (2023, 2023),
                                          (2032, 2032), (2033, None)])
def test_requirement_cohort_respects_supported_data_range(year, expected):
    assert requirement_grad_year(f"农学相关专业，{year}年应届毕业生。") == expected


def test_unsupported_year_in_a_multiple_cohort_requirement_does_not_disappear():
    assert requirement_grad_year("2022届、2027届均可申请。") is None


@pytest.mark.parametrize("record", json.loads((ROOT / "tests/fixtures/beisen/legacy-cohort-requirements.json").read_text(encoding="utf-8")),
                         ids=lambda record: record["source_job_id"])
def test_real_legacy_requirements_keep_text_without_a_supported_cohort(record):
    assert requirement_grad_year(record["requirement"]) == record["expected_grad_year"]
