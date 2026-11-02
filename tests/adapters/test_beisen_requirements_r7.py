"""逐源真实要求段与项目配置共同验收，不能只证明解析函数本身正确。"""

import json
from pathlib import Path

import httpx
import pytest

from jobradar.adapters.beisen import BeisenAdapter
from jobradar.adapters.hotjob import HotjobAdapter
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
