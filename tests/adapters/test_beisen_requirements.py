"""2026-11-02逐源回读的北森Require字段；仅在核验租户显式启用。"""

import json
from pathlib import Path

import httpx
import pytest

from jobradar.adapters.beisen import BeisenAdapter
from jobradar.models import SourceConfig

FX=Path(__file__).parents[1]/'fixtures/beisen/verified-requirements.json'


def adapter(*, enabled=True):
    return BeisenAdapter(SourceConfig(id='beisen-evidence',company='字段回归样本',adapter='beisen',
        enabled=False,params={'tenant':'example','detail_fields':enabled},
        recruit_types=['campus','social','intern']),httpx.Client())


@pytest.mark.parametrize('evidence',json.loads(FX.read_text(encoding='utf-8')),ids=lambda r:r['source_id'])
def test_verified_requirement_supplies_explicit_cohort(evidence):
    assert adapter().normalize(evidence['raw']).grad_year==evidence['expected_grad_year']
    assert adapter(enabled=False).normalize(evidence['raw']).grad_year is None


def test_social_and_missing_requirements_never_gain_a_cohort():
    raw={'Id':'sample','JobAdName':'工程师','CategoryId':'1','Require':'2027届本科及以上毕业生。'}
    assert adapter().normalize(raw).grad_year is None
    raw.update(CategoryId='2',Require=None)
    assert adapter().normalize(raw).grad_year is None


def test_title_evidence_keeps_priority():
    raw={'Id':'sample','JobAdName':'2027届工程师','CategoryId':'2','Require':'2026届本科毕业生。'}
    assert adapter().normalize(raw).grad_year==2027
