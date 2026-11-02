import httpx
import pytest

from jobradar.adapters.base import make_client
from jobradar.adapters.tencent import TencentAdapter
from jobradar.models import SourceConfig


@pytest.mark.parametrize(
    "raw_url,expected",
    [
        (
            "https:////tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Singapore/Engineer_R104904",
            "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Singapore/Engineer_R104904",
        ),
        (
            "//tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Engineer_R104904",
            "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Engineer_R104904",
        ),
        ("javascript:alert(1)", "https://careers.tencent.com/jobdesc.html?postId=123"),
    ],
)
def test_public_post_url_is_a_valid_http_address(raw_url, expected):
    source = SourceConfig(id="tencent", company="腾讯", adapter="tencent", enabled=False)
    with make_client(httpx.MockTransport(lambda _: None)) as client:
        job = TencentAdapter(source, client).normalize(
            {"PostId": 123, "RecruitPostName": "Engineer", "PostURL": raw_url}
        )
    assert job.url == expected
