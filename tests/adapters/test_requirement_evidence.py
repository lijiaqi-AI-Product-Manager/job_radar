"""要求段的届次证据必须表达单一届次，不把多届、范围或排除条件改成单届。"""

import pytest

from jobradar.adapters.hotjob import verified_detail_fields


@pytest.mark.parametrize("requirement", [
    # 一汽真实任职要求片段；只有末尾2027紧邻“届”，前一个2026也属于申请范围。
    "国家全日制统招本科及以上学历的2026、2027届毕业生。",
    "2026/2027届本科毕业生，材料或机械专业。",
    "2026和2027届应届毕业生，专业对口。",
    "2026至2027届应届毕业生。",
    "2027届及以后毕业生，熟悉Python。",
    "2027届（含）以前毕业生。",
    "不接受2027届毕业生。",
    "非2027届应届毕业生。",
])
def test_multiple_open_or_excluded_cohorts_remain_unknown(requirement):
    assert verified_detail_fields(requirement)["grad_year"] is None


@pytest.mark.parametrize("requirement, expected", [
    ("2027届应届本科学历及以上毕业生、机械、动力等相关专业。", 2027),
    ("2027年应届毕业生，硕士及以上学历。", 2027),
    ("1、2027届本科及以上毕业生。2、2027届毕业生具有相关实习经验优先。", 2027),
    ("2026年公司成立，2027届应届毕业生。", 2027),
    ("本科及以上学历，具有相关实习经验。", None),
    ("2026届或2027届均可投递。", None),
])
def test_explicit_single_cohort_and_unrelated_calendar_year(requirement, expected):
    assert verified_detail_fields(requirement)["grad_year"] == expected
