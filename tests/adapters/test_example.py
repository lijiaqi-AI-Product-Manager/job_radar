"""适配器专属测试：断言字段映射。新适配器请照此改写，并至少覆盖一条真实记录的每个关键字段。"""

from pathlib import Path

import httpx
import yaml

from jobradar.adapters.example import ExampleAdapter
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "example"


def run():
    source = SourceConfig(**yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8")))
    adapter = ExampleAdapter(source, httpx.Client(transport=ReplayTransport(FX)), sleep=lambda s: None)
    return list(adapter.fetch_all())


def test_field_mapping():
    j = run()[0]
    assert j.id == "example-corp:101"
    assert j.company == "示例公司"
    assert j.title == "后端开发工程师（校招）"
    assert j.recruit_type == "campus"
    assert j.cities == ["深圳", "北京"]
    assert (j.grad_year, j.batch, j.degree_min) == (2027, "正式批", "本科")
    assert j.url == "https://careers.example.invalid/job/101"
    assert "Go" in j.requirements


def test_intern_and_null_batch():
    j = run()[1]
    assert (j.recruit_type, j.batch, j.grad_year) == ("intern", None, 2028)


def test_record_without_title_is_skipped():
    assert [j.source_job_id for j in run()] == ["101", "102"]
