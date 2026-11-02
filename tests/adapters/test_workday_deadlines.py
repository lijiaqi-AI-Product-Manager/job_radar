"""Workday匿名CXS详情明确提供的endDate，不从发布日期反推。"""

import json
from pathlib import Path

import httpx
import pytest

from jobradar.adapters.workday import WorkdayAdapter
from jobradar.models import SourceConfig

FX=Path(__file__).parents[1]/'fixtures/workday/closing-date-evidence.json'


def adapter(params):
    return WorkdayAdapter(SourceConfig(id='workday-date',company='真实日期回归样本',adapter='workday',
        params=params,enabled=False,recruit_types=['social']),httpx.Client())


@pytest.mark.parametrize('record',json.loads(FX.read_text(encoding='utf-8')),
                         ids=lambda r:r['source_id']+'-'+r['expected_apply_end'])
def test_public_cxs_closing_date_is_preserved(record):
    job=adapter(record['params']).normalize(record['raw'])
    assert job.apply_end==record['expected_apply_end']


@pytest.mark.parametrize('value',[None,'','0001-01-01','9999-12-31','2026-02-30','2026-11-31'])
def test_missing_sentinel_or_impossible_closing_dates_remain_unknown(value):
    raw={'externalPath':'/job/example','title':'Engineer',
         'detail':{'startDate':'2026-10-01','endDate':value}}
    assert adapter({'host':'example.invalid','tenant':'example','site':'careers'}).normalize(raw).apply_end is None
