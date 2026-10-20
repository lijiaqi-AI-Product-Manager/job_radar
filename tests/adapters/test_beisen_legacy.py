from pathlib import Path

import httpx
import yaml

from jobradar.adapters.beisen_legacy import BeisenLegacyAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "beisen_legacy"


def source(**params):
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data["params"], **params}
    return SourceConfig(**data)


def run(src=None):
    a = BeisenLegacyAdapter(src or source(), httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(a.fetch_all())


def test_two_pages_distinct_jobs():
    jobs = run()
    assert len(jobs) == 30 and len({j.id for j in jobs}) == 30


def test_row_mapping_of_real_record():
    j = next(j for j in run() if j.source_job_id == "311047525")
    assert j.title == "软件工程师(J11999)"
    assert j.company == "中国船舶集团"
    assert j.recruit_type == "campus"
    assert j.cities == ["北京", "武汉"]
    assert j.department == "中船智海创新研究院有限公司"
    assert j.url == "https://cssc.zhiye.com/zpdetail/311047525"
    assert j.description is None and j.requirements is None  # 列表页无 JD 原文


def test_city_with_district_maps_to_city():
    j = next(j for j in run() if j.source_job_id == "311047528")
    assert j.cities == ["北京"]  # 原文"北京市-海淀区"


def test_stops_when_page_has_no_new_jobs():
    page = (FX / "001.txt").read_text(encoding="utf-8")
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=page)  # 每页都返回同样内容（越界时站点的表现）

    s = source()
    s.params = {k: v for k, v in s.params.items() if k != "max_pages"}
    a = BeisenLegacyAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert len(list(a.fetch_all())) == 15
    assert len(calls) == 2


def test_total_pages_footer_bounds_paging():
    html = '<tr><td><a title="A(J1)" href="/zpdetail/1?PageIndex=1">A</a></td></tr> 当前第1/1页'
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text=html)

    s = source()
    s.params = {k: v for k, v in s.params.items() if k != "max_pages"}
    a = BeisenLegacyAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert [j.title for j in a.fetch_all()] == ["A(J1)"] and len(calls) == 1
