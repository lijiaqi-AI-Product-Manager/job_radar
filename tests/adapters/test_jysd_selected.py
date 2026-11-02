"""已核验的有限公告集合不需要为每家公司重复扫描多年学校索引。"""

from datetime import date

import httpx
import pytest
from test_jysd import DETAIL, source

from jobradar.adapters.jysd import JysdAdapter


def test_selected_notices_read_the_complete_configured_set_without_index():
    seen=[]
    def handle(request):
        seen.append(request.url.path)
        return httpx.Response(200,text=DETAIL)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter=JysdAdapter(source(notice_ids=['123','124']),client,
                            reference_date=date(2026,10,31),sleep=lambda _:None)
        jobs=list(adapter.fetch_all())
    assert [j.source_job_id for j in jobs]==['123','124']
    assert seen==['/campus/view/id/123','/campus/view/id/124']


@pytest.mark.parametrize('ids',[[], '123', ['../user/login'], ['https://other.invalid/123'], ['123','123']])
def test_selected_notices_require_unique_numeric_public_ids(ids):
    with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,text=DETAIL))) as client:
        with pytest.raises(ValueError,match='notice_ids'):
            list(JysdAdapter(source(notice_ids=ids),client,sleep=lambda _:None).fetch_all())


def test_second_notice_failure_is_not_partial_success():
    def handle(request):
        return httpx.Response(200,text=DETAIL) if request.url.path.endswith('/123') else httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            list(JysdAdapter(source(notice_ids=['123','124']),client,
                             reference_date=date(2026,10,31),sleep=lambda _:None).fetch_all())


@pytest.mark.parametrize('title',[
    # 实际米哈游公告同时面向校招与全年实习，不能把整份公告写成唯一2027届。
    '米哈游27届秋季校招&28届及以后全年实习招聘',
    '某公司2026、2027届校园招聘',
    '某公司2027年度校园招聘',
])
def test_mixed_or_campaign_year_is_not_a_single_graduation_cohort(title):
    from jobradar.adapters.jysd import parse_detail
    raw={'item':{'id':'123','url':'https://example.invalid/campus/view/id/123'},
         'detail':parse_detail(DETAIL)}
    raw['detail']['title']=title
    with httpx.Client() as client:
        adapter=JysdAdapter(source(),client,reference_date=date(2026,10,31))
        assert adapter.normalize(raw).grad_year is None
