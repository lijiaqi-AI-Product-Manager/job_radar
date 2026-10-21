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


def test_page_distinct_jobs_all_with_jd():
    jobs = run()
    assert len(jobs) == 15 and len({j.id for j in jobs}) == 15
    assert all(j.description and j.requirements for j in jobs)  # 详情页补全 JD


def test_row_mapping_of_real_record():
    j = next(j for j in run() if j.source_job_id == "311047525")
    assert j.title == "软件工程师(J11999)"
    assert j.company == "中国船舶集团"
    assert j.recruit_type == "campus"
    assert j.cities == ["北京", "武汉"]
    assert j.department == "中船智海创新研究院有限公司"
    assert j.url == "https://cssc.zhiye.com/zpdetail/311047525"
    assert j.description == "1、参与平台控制系统软件及产品开发测试；\n2、组织控制系统软件测试、交付、维护及试验保障。"
    assert j.requirements.startswith("1、控制科学/计算机/软件、自动化相关专业背景；")


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
    assert len([c for c in calls if "PageIndex" in c]) == 2


def test_total_pages_footer_bounds_paging():
    html = '<tr><td><a title="A(J1)" href="/zpdetail/1?PageIndex=1">A</a></td></tr> 当前第1/1页'
    calls = []

    def handler(request):
        if "PageIndex" in str(request.url):
            calls.append(1)
        return httpx.Response(200, text=html)

    s = source()
    s.params = {k: v for k, v in s.params.items() if k != "max_pages"}
    a = BeisenLegacyAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert [j.title for j in a.fetch_all()] == ["A(J1)"] and len(calls) == 1


def test_job_show_link_variant():
    """科伦（kelun）的门户与变体 A 相同，只是详情链接为 /job_show/<id>（结构取自第 17 轮侦察）。"""
    html = """<tr>
            <td>
                <a title="科伦博泰-药效研究助理科学家/科学家(J13516)" href="/job_show/230947311?PageIndex=1" >科伦博泰-药效研究助理科学家/科学家(J13516)</a>
            </td>
                    <td title="研发临床类">研发临床类</td>
                    <td title="研发类子分公司">研发类子分公司</td>
            <td>1</td>
    </tr> 当前第1/1页"""
    s = source(tenant="kelun")
    s.params = {k: v for k, v in s.params.items() if k != "max_pages"}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html)))
    [j] = BeisenLegacyAdapter(s, client, sleep=lambda s: None).fetch_all()
    assert j.source_job_id == "230947311"
    assert j.title == "科伦博泰-药效研究助理科学家/科学家(J13516)"
    assert j.url == "https://kelun.zhiye.com/job_show/230947311"
    assert j.department == "研发临床类" and j.cities == []


B_LIST = """<a href="/campusxq?jobId=390852209&jc=2&c=&p=1^-1,3^-1&ky=" class="flex-between align-center">
    <span style="width: 15%;">技术研发类</span>
    <span style="width: 37%;">设计工艺协同研发工程师-张江（2027届校招）(J133...</span>
    <span style="width: 13%;">硕士、博士</span>
    <span style="width: 20%;">上海市</span>
    <span style="width: 15%;">2026-09-20</span>
</a> <a href="/campus/?PageIndex=22">22</a>"""
B_DETAIL = """<h2 class=" col26 b f20 lh30">设计工艺协同研发工程师-张江（2027届校招）(J13378)</h2>
<h3 class="f16 col333 b lh26 pb10">职位描述</h3>
<div class="xqm">1、负责工艺设计协同开发；<br />2、负责评估工艺节点性能。 </div>
<h3 class="f16 col333 b lh26 pb10 pt35">职位要求</h3>
<div class="xqm">微电子、集成电路等相关专业硕士及以上学历</div>"""


def test_variant_b_list_plus_detail():
    """中芯（smics）变体 B：列表为 /campusxq 链接 + span 列，标题可能被截断；完整标题与 JD 取详情页（第 25–26 轮侦察）。"""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "campusxq" in str(request.url):
            return httpx.Response(200, text=B_DETAIL)
        return httpx.Response(200, text=B_LIST)

    s = source(tenant="smics", variant="b")
    s.params = {k: v for k, v in s.params.items() if k != "max_pages"}
    a = BeisenLegacyAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    jobs = list(a.fetch_all())
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source_job_id == "390852209"
    assert j.title == "设计工艺协同研发工程师-张江（2027届校招）(J13378)"
    assert j.url == "https://smics.zhiye.com/campusxq?jobId=390852209&jc=2"
    assert j.cities == ["上海"] and j.degree_min == "硕士" and j.department == "技术研发类"
    assert j.grad_year == 2027
    assert j.description == "1、负责工艺设计协同开发；\n2、负责评估工艺节点性能。"
    assert j.requirements == "微电子、集成电路等相关专业硕士及以上学历"
    assert any("PageIndex=2" in c for c in calls)  # 第 2 页无新岗位后停止


def test_variant_b_detail_without_title_keeps_list_title():
    def handler(request):
        if "campusxq" in str(request.url):
            return httpx.Response(200, text="<html>no h2</html>")
        return httpx.Response(200, text=B_LIST.replace("(J133...", "(J13378)"))

    s = source(tenant="smics", variant="b")
    a = BeisenLegacyAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    [j] = a.fetch_all()
    assert j.title == "设计工艺协同研发工程师-张江（2027届校招）(J13378)" and j.description is None


A_DETAIL = """<div class="positiondetail-template6 ">
  <p class="title">工作职责：</p>
  <p>
      1、参与平台控制系统软件及产品开发测试；<br>2、组织控制系统软件测试、交付、维护及试验保障。
  </p>
  <br />
  <p class="title">任职资格：</p>
  <p>
      1、控制科学/计算机/软件、自动化相关专业背景；<br>2、有ARM/DSP/FPGA等开发经验；
  </p>
</div>"""


def test_variant_a_fetches_detail_for_jd():
    """变体 A 列表只有标题；JD 取详情页 <p>工作职责：</p><p>…</p>、<p>任职资格：</p><p>…</p>（第 29 轮侦察）。"""
    html = '<tr><td><a title="软件工程师(J11999)" href="/zpdetail/311047525?PageIndex=1">x</a></td></tr> 当前第1/1页'
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, text=A_DETAIL if "/zpdetail/" in request.url.path else html)

    s = source()
    s.params = {k: v for k, v in s.params.items() if k != "max_pages"}
    [j] = BeisenLegacyAdapter(s, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None).fetch_all()
    assert "/zpdetail/311047525" in seen
    assert j.description == "1、参与平台控制系统软件及产品开发测试；\n2、组织控制系统软件测试、交付、维护及试验保障。"
    assert j.requirements == "1、控制科学/计算机/软件、自动化相关专业背景；\n2、有ARM/DSP/FPGA等开发经验；"
