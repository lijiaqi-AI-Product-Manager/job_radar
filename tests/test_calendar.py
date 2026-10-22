"""招聘日历：人工条目校验（红线）、数据层自动生成、JD 关联/被挡提示、覆盖率、链接探活。"""

from pathlib import Path

import httpx
import pytest
import yaml

from helpers import T, make_job
from jobradar.core.queries import calendar_entries, calendar_stats, dead_links
from jobradar.models import Compliance, SourceConfig
from jobradar.pipeline import calendar as cal
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect

ROOT = Path(__file__).parent.parent
COMPLIANCE = Compliance(checked_on="2026-10-20", robots="not_applicable", terms="t")


def src(sid, company, adapter="beisen", **params):
    return SourceConfig(id=sid, company=company, adapter=adapter, params=params, compliance=COMPLIANCE)


TARGETS = {
    "sectors": {"互联网": ["字节跳动", "腾讯", "阿里巴巴"], "银行": ["招商银行"]},
    "aliases": {},
    "blocked": {"字节跳动": "滑块验证码"},
}


def manual(**kw):
    base = dict(
        id="bytedance-2027-qz", company="字节跳动", grad_year=2027, project_type="秋招正式批",
        tracks=[{"direction": "技术类", "roles": ["后端", "算法"]}],
        apply_start="2026-08-01", apply_end=None, cities=["北京", "上海"],
        apply_url="https://jobs.bytedance.com/campus",
        source={"type": "official_site", "name": "字节跳动校园招聘官网", "url": "https://jobs.bytedance.com/campus",
                "date": None},
        as_of="2026-10-21", jd={"status": "blocked", "url": "https://jobs.bytedance.com/campus"},
    )
    base.update(kw)
    return base


def test_match_targets_prefers_exact_over_substring():
    """「京东」不能把「京东方」抢走（2026-10-22 实测：京东方 366 个岗被挂在京东名下）。"""
    t = {"sectors": {"x": ["京东", "京东方"]}, "aliases": {}, "blocked": {}}
    matched = cal.match_targets(t, {"京东方", "京东"})
    assert matched["京东"] == ["京东"]
    assert matched["京东方"] == ["京东方"]


def test_match_targets_still_uses_aliases_and_substrings():
    t = {"sectors": {"x": ["中核集团", "美团", "网易"]}, "aliases": {"中核集团": ["中国核工业集团"]}, "blocked": {}}
    matched = cal.match_targets(t, {"中国核工业集团", "美团点评", "网易互娱"})
    assert matched["中核集团"] == ["中国核工业集团"]
    assert matched["美团"] == ["美团点评"]
    assert matched["网易"] == ["网易互娱"]   # 没有精确目标认领时，子串仍然生效


def write_entries(tmp_path, group, entries):
    d = tmp_path / "entries"
    d.mkdir(exist_ok=True)
    (d / f"{group}.yaml").write_text(yaml.safe_dump({"group": group, "entries": entries}, allow_unicode=True),
                                     encoding="utf-8")
    return d


@pytest.fixture
def cal_db():
    conn = connect(":memory:", "calendar")
    yield conn
    conn.close()


@pytest.fixture
def jobs(jobs_db):
    ingest_run(jobs_db, "tencent", [
        make_job(1, source_id="tencent", company="腾讯", recruit_type="campus", batch="正式批", grad_year=2027,
                 category="技术", subcategory="后端", title="后台开发", cities=["深圳"]),
        make_job(2, source_id="tencent", company="腾讯", recruit_type="campus", batch="正式批", grad_year=2027,
                 category="技术", subcategory="算法", title="算法工程师", cities=["北京", "深圳"]),
        make_job(3, source_id="tencent", company="腾讯", recruit_type="intern", batch=None, grad_year=2028,
                 category="产品", subcategory="产品经理", title="产品经理暑期实习", cities=["上海"]),
        make_job(4, source_id="tencent", company="腾讯", recruit_type="social", batch=None, grad_year=None,
                 title="高级后端", cities=["深圳"]),
    ], ts=T(20))
    return jobs_db


# ---------- 人工条目：红线校验 ----------

def test_manual_entry_valid_loads(tmp_path):
    [e] = cal.load_manual(write_entries(tmp_path, "字节跳动", [manual()]))
    assert e.group == "字节跳动" and e.project_type == "秋招正式批" and e.source.type == "official_site"


@pytest.mark.parametrize("bad, msg", [
    ({"project_type": "秋季招聘"}, "project_type"),
    ({"source": {"type": "official_site", "name": "牛客", "url": "https://www.nowcoder.com/discuss/1"}}, "第三方"),
    ({"source": {"type": "wechat", "name": "某公众号", "url": "https://example.com/a", "date": "2026-08-03"}}, "wechat"),
    ({"source": {"type": "wechat", "name": "字节跳动招聘", "url": None, "date": None}}, "date"),
    ({"source": {"type": "gov", "name": "国聘", "url": "https://www.example.com/x"}}, "gov"),
    ({"as_of": None}, "as_of"),
    ({"apply_start": "2026-09-01", "apply_end": "2026-08-01"}, "apply_end"),
    ({"jd": {"status": "official_page", "url": None}}, "url"),
    ({"jd": {"status": "linked"}}, "jd"),  # linked 只能由数据层自动判定
])
def test_manual_entry_red_lines(tmp_path, bad, msg):
    with pytest.raises(ValueError, match=msg):
        cal.load_manual(write_entries(tmp_path, "字节跳动", [manual(**bad)]))


def test_manual_ids_unique_across_files(tmp_path):
    write_entries(tmp_path, "字节跳动", [manual()])
    d = write_entries(tmp_path, "腾讯", [manual(company="腾讯")])
    with pytest.raises(ValueError, match="重复"):
        cal.load_manual(d)


def test_official_careers_subdomain_of_ugc_company_is_allowed(tmp_path):
    e = manual(source={"type": "official_site", "name": "B站招聘官网", "url": "https://jobs.bilibili.com/campus"})
    assert cal.load_manual(write_entries(tmp_path, "哔哩哔哩", [e]))


# ---------- 自动生成 ----------

def test_auto_entries_from_data_layer(jobs):
    entries = cal.auto_entries(jobs, [src("tencent", "腾讯", adapter="tencent")], TARGETS, as_of=T(20))
    by_type = {(e["project_type"], e["grad_year"]): e for e in entries}
    qz = by_type[("秋招正式批", 2027)]
    assert qz["origin"] == "auto" and qz["group_name"] == "腾讯" and qz["source_type"] == "data_layer"
    assert qz["tracks"] == [{"direction": "技术", "roles": ["后端", "算法"], "examples": ["后台开发", "算法工程师"]}]
    assert qz["cities"] == ["深圳", "北京"] and qz["open_jobs"] == 2 and qz["jd_status"] == "linked"
    assert qz["apply_url"] == "https://careers.tencent.com/search.html" and qz["observed_from"] == "2026-10-20"
    assert qz["apply_start"] is None and qz["apply_end"] is None  # 数据层不知道网申起止，不编
    assert by_type[("暑期实习", 2028)]["open_jobs"] == 1  # 标题写明"暑期实习"
    assert ("社招", None) in by_type


def test_portal_urls_per_adapter():
    assert cal.portal_url(src("b", "x", tenant="cicc"), "campus") == "https://cicc.zhiye.com/campus"
    assert cal.portal_url(src("b", "x", adapter="meituan"), "social") == "https://zhaopin.meituan.com/web/social"
    assert cal.portal_url(src("b", "x", adapter="tencent_campus"), "intern") == "https://join.qq.com/post.html"


# ---------- 构建 + 查询 ----------

@pytest.fixture
def built(tmp_path, jobs, cal_db):
    d = write_entries(tmp_path, "字节跳动", [manual(), manual(id="bytedance-2027-intern", project_type="日常实习")])
    write_entries(tmp_path, "腾讯", [manual(id="tencent-2027-qz", company="腾讯", apply_url="https://join.qq.com/",
                                            jd={"status": "none"},
                                            source={"type": "wechat", "name": "腾讯招聘", "date": "2026-08-10",
                                                    "url": "https://mp.weixin.qq.com/s/abc"})])
    cal.build(cal_db, jobs, manual=cal.load_manual(d), sources=[src("tencent", "腾讯", adapter="tencent")],
              targets=TARGETS, ts=T(21))
    return cal_db


def test_query_by_group_type_and_hint_for_blocked_jd(built):
    rows = calendar_entries(built, group="字节", project_type="秋招")
    assert [r["id"] for r in rows] == ["bytedance-2027-qz"]
    r = rows[0]
    assert r["origin"] == "manual" and r["jd_status"] == "blocked"
    assert r["hint"] == "字节跳动希望你去他们的招聘页逛一逛哦~"
    assert r["source"] == {"type": "official_site", "name": "字节跳动校园招聘官网",
                           "url": "https://jobs.bytedance.com/campus", "date": None}


def test_manual_entry_auto_links_jd_when_company_in_data_layer(built):
    [r] = calendar_entries(built, group="腾讯", origin="manual")
    assert r["jd_status"] == "linked" and r["jd_company"] == "腾讯" and r["open_jobs"] == 2  # 校招类：只数 campus
    assert r["hint"] is None


def test_query_filters_origin_and_grad_year(built):
    assert {r["origin"] for r in calendar_entries(built, group="腾讯")} == {"manual", "auto"}
    assert all(r["grad_year"] == 2028 for r in calendar_entries(built, grad_year=2028))


def test_open_on_uses_apply_window(built):
    ids = [r["id"] for r in calendar_entries(built, group="字节", open_on="2026-07-01")]
    assert ids == []  # 网申 8 月才开始
    assert "bytedance-2027-qz" in [r["id"] for r in calendar_entries(built, group="字节", open_on="2026-10-21")]


def test_stats_coverage(built):
    st = calendar_stats(built)
    assert st["targets"] == 4
    assert st["calendar_covered"] == 2 and st["jd_covered"] == 1  # 字节(日历)、腾讯(日历+JD)
    assert st["missing_calendar"] == ["阿里巴巴", "招商银行"]
    assert {s["sector"]: s["calendar_covered"] for s in st["by_sector"]} == {"互联网": 2, "银行": 0}


def test_rebuild_replaces_entries(built, jobs):
    before = len(calendar_entries(built, origin="auto"))
    cal.build(built, jobs, manual=[], sources=[], targets=TARGETS, ts=T(22))
    assert calendar_entries(built, origin="manual") == []  # 人工条目删掉后不残留
    after = calendar_entries(built, origin="auto")
    assert len(after) == before and all(r["apply_url"] is None for r in after)  # 数据层仍在；无源配置时没有入口


# ---------- 链接探活 ----------

def test_link_check_marks_dead_and_keeps_first_failed(built):
    def handler(req):
        return httpx.Response(404) if "bytedance" in str(req.url) else httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cal.check_links(built, client, ts=T(21), sleep=lambda s: None)
    cal.check_links(built, client, ts=T(22), sleep=lambda s: None)
    dead = dead_links(built)
    assert [d["url"] for d in dead] == ["https://jobs.bytedance.com/campus"]
    assert dead[0]["first_failed_at"] == T(21) and dead[0]["status"] == "dead"
    assert set(dead[0]["entries"]) == {"bytedance-2027-qz", "bytedance-2027-intern"}

    cal.check_links(built, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
                    ts=T(23), sleep=lambda s: None)
    assert dead_links(built) == []  # 恢复后不再列出


def test_link_check_network_error_is_error_not_dead(built):
    def handler(req):
        raise httpx.ConnectError("x")

    cal.check_links(built, httpx.Client(transport=httpx.MockTransport(handler)), ts=T(21), sleep=lambda s: None)
    rows = dead_links(built, include_errors=True)
    assert rows and all(r["status"] == "error" for r in rows)
    assert dead_links(built) == []


# ---------- 仓库里的真实条目 ----------

def test_repo_calendar_entries_are_valid():
    entries = cal.load_manual(ROOT / "calendar" / "entries")
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    names = {n for ns in targets["sectors"].values() for n in ns}
    for e in entries:
        assert e.group in names, f"{e.id}: 集团 {e.group} 不在 targets/top_companies.yaml"


def test_link_check_respects_robots(built):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            body = "User-agent: *\nDisallow: /\n" if req.url.host == "jobs.bytedance.com" else ""
            return httpx.Response(200, text=body)
        return httpx.Response(200)

    counts = cal.check_links(built, httpx.Client(transport=httpx.MockTransport(handler)), ts=T(21),
                             sleep=lambda s: None)
    assert counts["skipped_robots"] >= 1
    assert not [u for u in seen if u.startswith("https://jobs.bytedance.com/") and "robots" not in u]
