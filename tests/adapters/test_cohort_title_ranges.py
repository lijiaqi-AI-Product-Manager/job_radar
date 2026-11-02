"""真实公开标题中的多届范围，不能由标题或要求段压成单届。"""

import json
from pathlib import Path

import httpx
import pytest

from jobradar.adapters.beisen import BeisenAdapter
from jobradar.adapters.hotjob import HotjobAdapter
from jobradar.models import SourceConfig

ROWS = json.loads((Path(__file__).parents[1] / "fixtures/beisen/ambiguous-cohort-titles.json").read_text(encoding="utf-8"))


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
