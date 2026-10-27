"""北森旧版门户「变体 C」（社招 `/socialxq?jobId=`）契约测试。

这个变体是 2026-10-27 由「官网 → ATS 反查」发现的：zofund 等一批社招门户
走的是 `/socialxq?jobId=` 而不是 `/zpdetail/`，旧正则一行都匹配不到，
这些门户一直被当成「空租户」（接口 302 → /404）。

两条必须守住的契约：
  1. 列表表格 → 岗位（标题在 `<a><span>` 里，城市按内容识别，不是按列序号猜）；
  2. 详情页 JD 必须抽出来 —— 而且请求必须是 `?jobId=` 查询串形式。
     服务端对 `/socialxq/123` 也回 200，但那是**没有正文的空壳页**，
     用路径模板拼 URL 会静默丢 JD（真实踩过）。
"""
from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.adapters.beisen_legacy import BeisenLegacyAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "beisen_legacy_c"


def source() -> SourceConfig:
    return SourceConfig(**yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8")))


def run(src: SourceConfig | None = None, transport=None):
    a = BeisenLegacyAdapter(src or source(),
                            httpx.Client(transport=transport or ReplayTransport(FX)),
                            sleep=lambda s: None)
    return list(a.fetch_all())


def test_lists_three_jobs_from_one_page():
    jobs = run()
    assert len(jobs) == 3
    assert len({j.id for j in jobs}) == 3


def test_social_record_mapping():
    j = next(j for j in run() if j.source_job_id == "621155633")
    assert j.title == "电商金融产品岗"
    assert j.company == "中欧基金"
    assert j.recruit_type == "social"
    assert j.cities == ["上海"]
    assert j.department == "中欧财富"
    assert j.publish_at == "2026-10-15"
    assert j.url == "https://zofund.zhiye.com/socialxq?jobId=621155633"
    assert j.description.startswith("1、负责公司重点公募产品池的定期跟踪和维护")


def test_every_job_has_jd():
    jobs = run()
    assert all(j.description for j in jobs)
    assert all(j.requirements for j in jobs)
    assert "硕士及以上学历" in next(j for j in jobs if j.source_job_id == "621155633").requirements


def test_detail_url_uses_query_string_not_path():
    """详情必须是 `?jobId=` 查询串：路径形式服务端也回 200，但正文是空的。"""
    calls: list[str] = []
    listing = (FX / "001.txt").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        # 列表页要回真内容，否则一条岗位都没有、也就不会去请求详情
        return httpx.Response(200, text=listing if "PageIndex" in str(request.url) else "<html></html>")

    run(transport=httpx.MockTransport(handler))
    detail_calls = [c for c in calls if "socialxq" in c]
    assert detail_calls, calls
    assert all("?jobId=" in c for c in detail_calls), detail_calls


@pytest.mark.parametrize("variant", ["a", ""])
def test_variant_c_is_opt_in(variant):
    """不写 variant: c 时不能走社招分支（避免把 zpdetail 门户当 xq 门户抓空）。"""
    src = source()
    src.params = {**src.params, "variant": variant} if variant else \
        {k: v for k, v in src.params.items() if k != "variant"}
    src.params["portal"] = "campus"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text='<tr><td><a title="A(J1)" href="/zpdetail/9">A</a></td></tr>')

    with httpx.Client(transport=httpx.MockTransport(handler)) as _:
        a = BeisenLegacyAdapter(src, _, sleep=lambda s: None)
        list(a.fetch_all())
    assert any("zpdetail" in c for c in calls), calls
