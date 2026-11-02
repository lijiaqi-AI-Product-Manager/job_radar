"""公开列表出错、中途截断或分页重复不能成为成功的部分岗位集合。"""

import httpx
import pytest
from test_yunjiuye import JOBS, _source

from jobradar.adapters.yunjiuye import YunjiuyeAdapter


@pytest.mark.parametrize('second',[
    '<html>登录或错误页</html>',
    {'code':0,'data':[]},
    {'code':1,'data':{}},
    {'code':1,'data':[{'company_name':'缺少岗位标识'}]},
])
def test_second_page_errors_reject_the_whole_collection(second):
    page=[{**JOBS['data'][0],'publish_id':str(i)} for i in range(100)]
    def handle(request):
        if request.url.params.get('start')=='1':
            return httpx.Response(200,json={'code':1,'data':page})
        return httpx.Response(200,text=second) if isinstance(second,str) else httpx.Response(200,json=second)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises((ValueError,RuntimeError)):
            list(YunjiuyeAdapter(_source(fetch_detail=False),client,sleep=lambda _:None).fetch_all())


def test_repeated_full_page_is_not_a_complete_collection():
    page=[{**JOBS['data'][0],'publish_id':str(i)} for i in range(100)]
    with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'code':1,'data':page}))) as client:
        with pytest.raises(ValueError,match='分页'):
            list(YunjiuyeAdapter(_source(fetch_detail=False),client,sleep=lambda _:None).fetch_all())


def test_page_cap_cannot_silently_accept_a_full_last_page():
    page=[{**JOBS['data'][0],'publish_id':str(i)} for i in range(100)]
    with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'code':1,'data':page}))) as client:
        with pytest.raises(ValueError,match='未完成'):
            list(YunjiuyeAdapter(_source(max_pages=1,fetch_detail=False),client,sleep=lambda _:None).fetch_all())
