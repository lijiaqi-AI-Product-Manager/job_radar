"""真实公开标题中的多届范围，不能由标题或要求段压成单届。"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from jobradar.adapters.beisen import BeisenAdapter
from jobradar.adapters.feishu_atsx import FeishuAtsxAdapter
from jobradar.adapters.hotjob import HotjobAdapter
from jobradar.models import SourceConfig
from jobradar.normalize import grad_year_from_text, uncertain_title_cohort

ROWS = json.loads((Path(__file__).parents[1] / "fixtures/beisen/ambiguous-cohort-titles.json").read_text(encoding="utf-8"))
TITLES = sorted({row["title"] for row in json.loads((Path(__file__).parents[2] / "targets/cohort_title_corrections.json").read_text(encoding="utf-8"))["rows"]})


@pytest.mark.parametrize("title", TITLES)
def test_real_four_and_two_digit_ranges_remain_unknown(title):
    assert uncertain_title_cohort(title)
    assert grad_year_from_text(title) is None
    assert grad_year_from_text(title, loose=True) is None


@pytest.mark.parametrize("title", ["初级 EMS 产品经理（25-26届）", "24/25届-销售运营", "往届生社招专属通道（ 非2027届可投 ）"])
@pytest.mark.parametrize("project", ["2027届校园招聘", "Mstar计划"])
def test_feishu_project_or_jd_cannot_override_title_range(monkeypatch, title, project):
    import jobradar.adapters.feishu_atsx as module

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 2)

    monkeypatch.setattr(module, "date", FixedDate)
    source = SourceConfig(id="range-evidence", company="示例公司", adapter="feishu_atsx", enabled=False)
    raw = {"id":"example", "title":title, "job_subject":{"name":project},
           "recruit_type":{"name":"校园招聘"}, "requirement":"2027届本科毕业生。",
           "publish_time":int(datetime(2026, 11, 2, tzinfo=UTC).timestamp()*1000)}
    with httpx.Client() as client:
        adapter = FeishuAtsxAdapter(source, client)
        assert adapter.normalize({**raw,"title":"研发工程师"}).grad_year == 2027
        assert adapter.normalize(raw).grad_year is None


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["source_job_id"])
@pytest.mark.parametrize("details", [False, True])
@pytest.mark.parametrize("kind", ["beisen", "hotjob"])
def test_real_range_title_never_becomes_a_single_cohort(row, details, kind):
    source = SourceConfig(id="range-evidence", company="示例公司", adapter=kind, enabled=False,
                          params={"tenant": "example", "detail_fields": details})
    with httpx.Client() as client:
        if kind == "beisen":
            raw = {"Id": row["source_job_id"], "JobAdName": row["title"], "CategoryId": "2",
                   "Require": "2027届本科毕业生，具有团队合作能力。"}
            job = BeisenAdapter(source, client).normalize(raw)
        else:
            raw = {"list": {"postId": row["source_job_id"], "postName": row["title"]},
                   "recruit_type": "campus", "detail": {"serviceCondition": "2027届本科毕业生，具有团队合作能力。"}}
            job = HotjobAdapter(source, client).normalize(raw)
    assert job.grad_year == row["expected_grad_year"]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["source_job_id"])
def test_beisen_html_keeps_explicit_title_range_unknown(row):
    source = SourceConfig(id="range-evidence", company="示例公司", adapter="beisen", enabled=False,
                          params={"tenant": "example"}, recruit_types=["campus", "intern", "social"])
    raw = {"id": row["source_job_id"], "title": row["title"], "kind": "校园招聘",
           "detail": {"title": row["title"], "任职要求": "2027届本科毕业生，具有团队合作能力。"}}
    with httpx.Client() as client:
        assert BeisenAdapter(source, client).normalize(raw).grad_year is None
