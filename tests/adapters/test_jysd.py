"""才立方公开列表/公告的离线解析与归属、日期边界。"""

import base64
import zlib
from datetime import date
from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.jysd import JysdAdapter, parse_detail, parse_index, public_html
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig


def source(**params):
    return SourceConfig(id="jysd-example", company="某公司", adapter="jysd", source_kind="aggregator",
                        params={"host": "example.invalid", "match": ["某公司股份有限公司"], **params},
                        compliance={"checked_on": "2026-10-31", "robots": "absent", "terms": "公开招聘公告"})


def widget(fragment, *, before=104, after=39):
    encoded = base64.b64encode((" " * after + fragment).encode()).decode()
    packed = base64.b64encode(zlib.compress((" " * before + encoded).encode())).decode()
    return ('<section id="content9934"></section><script>$("#content9934").each(function() {'
            f'$(this).replaceWith(Base64.decode(unzip("{packed}").substr({before})).substr({after}));'
            '});</script>')


ITEM = ('<ul class="infoList"><li><a href="/campus/view/id/123">某公司2027届校园招聘</a></li>'
        '<li>2026-10-30 10:00:00</li></ul>')
DETAIL = '''<title>某公司2027届校园招聘</title><div class="details-title"><h5>某公司2027届校园招聘</h5>
<a class="name text-primary" href="/company/view/id/1">某公司股份有限公司</a>
<span class="expired_time">过期时间：2026-11-30</span></div>
<div class="title-message">发布时间：2026-10-30 10:00 浏览次数：12</div>
<div class="aContent"><p>岗位：后端开发工程师</p><p>工作地点：深圳</p>
<p>任职要求：计算机相关专业，熟悉 Python。</p><p>网申截止时间：2026年11月15日。</p></div>
<footer>其他无关招聘</footer>'''


def test_public_literal_html_is_decoded_without_executing_scripts():
    html = public_html(widget(ITEM))
    assert ITEM in html
    parsed = parse_index('<div class="campus-index-front-list">' + html + '</div>', "https://example.invalid")
    assert parsed["items"] == [{"id": "123", "title": "某公司2027届校园招聘",
                                 "url": "https://example.invalid/campus/view/id/123", "published": "2026-10-30"}]
    assert parsed["next"] is None


@pytest.mark.parametrize("html", ["<html>登录</html>", '<div class="campus-index-front-list"></div>'])
def test_unrecognized_or_login_list_is_not_accepted_as_an_empty_success(html):
    with pytest.raises(ValueError):
        parse_index(html, "https://example.invalid")


def test_compressed_content_is_bounded_and_corruption_is_reported():
    with pytest.raises(ValueError):
        public_html(widget("x" * 2_000_001))
    with pytest.raises(ValueError):
        public_html(widget(ITEM).replace('unzip("', 'unzip("not-valid-'))


def test_next_links_must_stay_in_public_same_origin_index():
    html = '<div class="campus-index-front-list">' + ITEM
    with pytest.raises(ValueError):
        parse_index(html + '<li class="next"><a href="https://other.invalid/campus/index/page/2">下一页</a></li></div>',
                    "https://example.invalid")


def test_detail_keeps_announcement_expiry_separate_from_application_deadline():
    result = parse_detail(DETAIL)
    assert result["company"] == "某公司股份有限公司" and result["listing_end"] == "2026-11-30"
    assert result["apply_end"] == "2026-11-15"
    assert "后端开发工程师" in result["description"] and "其他无关" not in result["description"]
    no_deadline = parse_detail(DETAIL.replace("网申截止时间：2026年11月15日。", "请以招聘网站为准。"))
    assert no_deadline["apply_end"] is None


def test_multiple_deadlines_are_not_collapsed_to_an_invented_group_window():
    result = parse_detail(DETAIL.replace('</div>\n<footer>', '<p>报名截止时间：2026年11月20日。</p></div>\n<footer>'))
    assert result["apply_end"] is None


def test_normalization_checks_company_expiry_and_title_type():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        adapter = JysdAdapter(source(), client, reference_date=date(2026, 10, 31))
        raw = {"item": {"id": "123", "url": "https://example.invalid/campus/view/id/123", "title": "某公司2027届校园招聘"},
               "detail": parse_detail(DETAIL)}
        job = adapter.normalize(raw)
        assert job.grad_year == 2027 and job.recruit_type == "campus" and job.cities == ["深圳"]
        assert job.apply_end == "2026-11-15" and job.degree_min is None
        for updates in ({"company": "某公司股份有限公司分公司"}, {"listing_end": "2026-10-30"},
                        {"title": "某公司高层次人才招聘"}):
            with pytest.raises(SkipRecord):
                adapter.normalize({"item": raw["item"], "detail": {**raw["detail"], **updates}})


def test_private_contacts_are_not_part_of_indexed_description():
    result = parse_detail(DETAIL.replace('</div>\n<footer>', '<p>联系人：某老师</p><p>手机：13812345678</p>'
                                        '<p>邮箱：hr.person@example.invalid</p></div>\n<footer>'))
    assert "13812345678" not in result["description"] and "某老师" not in result["description"]
    assert "hr.person@" not in result["description"]


def test_publish_date_uses_its_label_instead_of_earlier_expiry_date():
    html = DETAIL.replace('发布时间：2026-10-30 10:00', '过期时间：2026-12-31 发布时间：2026-10-30 10:00')
    assert parse_detail(html)["published"] == "2026-10-30"


def test_work_location_does_not_store_qualification_or_prose_as_a_city():
    html = DETAIL.replace('工作地点：深圳', '工作地点：北京、成都、南京等全国直辖、省会城市均有岗位。学历要求：本科')
    cities = parse_detail(html)["cities"]
    assert "北京" in cities and "成都" in cities
    assert all(len(city) <= 5 and "学历" not in city and "岗位" not in city for city in cities)


def test_publication_date_can_be_in_header_operation_sibling():
    html = DETAIL.replace('</div>\n<div class="title-message">发布时间：2026-10-30 10:00 浏览次数：12</div>',
                          '<div class="operation">发布时间：2026-10-30 10:00</div></div>')
    assert parse_detail(html)["published"] == "2026-10-30"


def test_recorded_sample_is_minimized_before_writing_and_keeps_public_structure():
    raw = DETAIL.replace('</div>\n<footer>', '<p>联系人：某老师</p><p>电话：13812345678</p></div>\n<footer>')
    recorded = JysdAdapter.fixture_transform(raw.encode(), 'text/html').decode()
    assert '13812345678' not in recorded and '某老师' not in recorded and '其他无关' not in recorded
    assert parse_detail(recorded)["company"] == "某公司股份有限公司"
    assert "后端开发工程师" in parse_detail(recorded)["description"]
    listing = '<div class="campus-index-front-list">' + widget(ITEM) + '</div><footer>电话：13812345678</footer>'
    recorded = JysdAdapter.fixture_transform(listing.encode(), 'text/html').decode()
    assert '13812345678' not in recorded and 'Base64.decode' in recorded
    assert parse_index(recorded, 'https://example.invalid')["items"][0]["id"] == '123'


def test_live_recording_replays_full_entity_jd_and_dates():
    directory = Path(__file__).parents[1] / 'fixtures/jysd_jysd-zzu-kunlun'
    src = SourceConfig(**yaml.safe_load((directory / 'source.yaml').read_text(encoding='utf-8')))
    with httpx.Client(transport=ReplayTransport(directory)) as client:
        jobs = list(JysdAdapter(src, client, reference_date=date(2026, 10, 31), sleep=lambda _: None).fetch_all())
    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == '昆仑万维科技股份有限公司' and job.source_job_id == '1019971'
    assert job.title == '昆仑万维科技股份有限公司2027届校园招聘'
    assert job.grad_year == 2027 and job.recruit_type == 'campus'
    assert job.publish_at == '2026-10-21' and job.apply_end is None
    assert job.url == 'https://job.zzu.edu.cn/campus/view/id/1019971'
    assert len(job.description) > 500 and job.degree_min is None


def test_incomplete_index_cannot_be_reported_as_success(monkeypatch):
    import jobradar.adapters.jysd as module

    monkeypatch.setattr(module, '_INDEX_CACHE', {})
    first = ('<div class="campus-index-front-list">' + ITEM
             + '<li class="next"><a href="/campus/index/page/2">下一页</a></li></div>')
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=first))) as client:
        adapter = JysdAdapter(source(max_pages=1), client, sleep=lambda _: None)
        with pytest.raises(ValueError, match='未完成'):
            list(adapter.fetch_all())


def test_complete_index_is_shared_between_companies_and_repeated_pages_fail(monkeypatch):
    import jobradar.adapters.jysd as module

    monkeypatch.setattr(module, '_INDEX_CACHE', {})
    seen = []

    def handle(request):
        seen.append(request.url.path)
        page = '<div class="campus-index-front-list">' + ITEM + '</div>'
        return httpx.Response(200, text=page if request.url.path == '/campus/index' else DETAIL)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        for _ in range(2):
            assert len(list(JysdAdapter(source(), client, reference_date=date(2026, 10, 31),
                                       sleep=lambda _: None).fetch_all())) == 1
    assert seen == ['/campus/index', '/campus/view/id/123', '/campus/view/id/123']


def test_real_last_page_self_link_is_terminal_only_with_pager_evidence():
    path = Path(__file__).parents[1] / 'fixtures/jysd_pagination/last.html'
    result = parse_index(path.read_text(encoding='utf-8'), 'https://job.zzu.edu.cn')
    assert result["items"] and result["next"] is None
    assert result["current_page"] == result["last_page"] == 164


def test_self_link_before_declared_last_page_is_an_error():
    html = ('<div class="campus-index-front-list">' + ITEM +
            '<li class="page selected"><a href="/campus/index/page/2">2</a></li>'
            '<li class="page"><a href="/campus/index/page/5">5</a></li>'
            '<li class="next"><a href="/campus/index/page/2">下一页</a></li></div>')
    with pytest.raises(ValueError, match='分页'):
        parse_index(html, 'https://example.invalid')
