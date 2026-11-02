"""雇主网申截止句和完整网申时间段，不使用学校公告展示有效期。"""

import json
from pathlib import Path

import pytest
from test_jysd import DETAIL

from jobradar.adapters.jysd import parse_detail


def with_deadline(text):
    return DETAIL.replace('网申截止时间：2026年11月15日。',text)


def test_real_bank_deadline_precedes_school_listing_expiry():
    path=Path(__file__).parents[1]/'fixtures/jysd_deadlines/bank-deadline.json'
    record=json.loads(path.read_text(encoding='utf-8'))
    result=parse_detail(with_deadline(record['deadline_excerpts'][0]))
    assert result['apply_end']==record['expected_apply_end']=='2026-10-09'
    assert result['apply_end']<record['listing_end']


@pytest.mark.parametrize('text,expected',[
    ('报名截止时间为北京时间2026年10月9日24点。','2026-10-09'),
    ('投递截止日期至2026年11月15日。','2026-11-15'),
    ('报名时间：2026年9月1日至2026年11月15日。','2026-11-15'),
    ('网申时间：2026.09.01-2026.11.15。','2026-11-15'),
    ('简历投递时间：即日起至2026年11月15日。','2026-11-15'),
    ('报名时间：2026年12月1日至2026年11月15日。',None),
    ('网申时间：9月1日至11月15日。',None),
    ('公司资产截至2026年11月15日为100亿元。',None),
    ('宣讲时间：2026年9月1日至2026年11月15日。',None),
    ('网申截止时间为2026年11月31日。',None),
    ('网申时间：2026年9月1日至2026年11月15日；报名截止：2026年11月20日。',None),
])
def test_only_explicit_unambiguous_application_windows_supply_an_end(text,expected):
    assert parse_detail(with_deadline(text))['apply_end']==expected
