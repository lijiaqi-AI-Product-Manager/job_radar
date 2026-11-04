"""文档中的真实命令经过离线执行；网络命令仅校验参数，不能在测试中联网。"""

import importlib.util
from contextlib import closing
from pathlib import Path

import pytest

from helpers import make_job
from jobradar import cli, local
from jobradar.pipeline.calendar import ManualEntry, build
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import connect

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("readme_examples", ROOT / "scripts/check_readme_examples.py")
examples = importlib.util.module_from_spec(SPEC)
if Path(SPEC.origin).exists():
    SPEC.loader.exec_module(examples)


@pytest.fixture
def documented_home(tmp_path, monkeypatch):
    ts = "2026-11-01T00:00:00Z"
    monkeypatch.setattr(cli, "now_ts", lambda: ts)
    monkeypatch.setattr(local, "now_ts", lambda: ts)
    monkeypatch.setattr(cli, "_download", lambda *a, **kw: pytest.fail("documentation checks must not download"))
    rows = []
    for i, (company, kind, city, category, subcategory, title) in enumerate([
        ("腾讯", "campus", "深圳", "技术", "算法", "大模型算法工程师"),
        ("复星医药", "campus", "上海", "医药", "医药研发", "研发工程师"),
        ("示例公司", "intern", "上海", "技术", "算法", "算法实习生"),
        ("示例公司", "campus", "苏州", "职能", "财务审计", "会计专员"),
        ("示例公司", "campus", "北京", "财务", None, "财务专员"),
        ("美团", "social", "北京", "技术", "算法", "算法工程师"),
        ("药明康德", "campus", "上海", "医药", "医药研发", "化学研发工程师"),
        ("正大天晴", "campus", "南京", "医药", "医药研发", "化学研发研究员"),
        ("示例门店", "intern", "无锡", "门店零售", "门店运营", "门店实习生"),
    ], 1):
        rows.append(make_job(i, source_id="documented", company=company, recruit_type=kind,
                             cities=[city], category=category, subcategory=subcategory, title=title,
                             grad_year=2027, apply_end="2026-11-20", description="PyTorch 多模态大模型"))
    with closing(connect(tmp_path / "jobs.db", "jobs")) as jobs, \
            closing(connect(tmp_path / "jd_text.db", "text")) as texts, \
            closing(connect(tmp_path / "calendar.db", "calendar")) as calendar:
        ingest_run(jobs, "documented", rows, ts=ts)
        upsert_texts(texts, rows, ts=ts)
        manual = [ManualEntry(id=f"manual-{i}", group=group, grad_year=2027, project_type="秋招正式批",
                              cities=["北京"], tracks=[{"direction":"技术类","roles":["算法"]}],
                              apply_start="2026-10-01", apply_end="2026-11-30", as_of="2026-11-01",
                              source={"type":"official_site","name":"离线示例"})
                  for i,group in enumerate(("阿里巴巴", "字节跳动"))]
        build(calendar, jobs, manual=manual, sources=[], targets={"sectors":{}}, ts=ts)
    return tmp_path


def test_readme_and_skill_queries_work_on_a_readonly_snapshot(documented_home):
    before = {p.name:p.read_bytes() for p in documented_home.glob("*.db")}
    result = examples.check_examples(documented_home, root=ROOT)
    assert not [r for r in result if not r["ok"]], result
    assert any("--category 财务" in r["command"] and r["count"] == 1 for r in result)
    assert any(r["command"] == "jobradar update" and r["mode"] == "syntax" for r in result)
    assert len(result) >= 20
    assert all(p.read_bytes() == before[p.name] for p in documented_home.glob("*.db"))


def test_bad_documented_arguments_are_a_gate_failure(tmp_path, documented_home):
    (tmp_path / "README.md").write_text("```bash\njobradar search --made-up-option value\n```", encoding="utf-8")
    result = examples.check_examples(documented_home, root=tmp_path)
    assert len(result) == 1 and not result[0]["ok"]


def test_concrete_zero_result_example_is_not_counted_as_passing(tmp_path, documented_home):
    (tmp_path / "README.md").write_text("```bash\njobradar search --city 拉萨\n```", encoding="utf-8")
    result = examples.check_examples(documented_home, root=tmp_path)
    assert len(result) == 1 and result[0]["count"] == 0 and not result[0]["ok"]


def test_release_gate_includes_actual_documented_query_results(tmp_path, documented_home):
    spec = importlib.util.spec_from_file_location("release_check_examples", ROOT / "scripts/release_check.py")
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    (tmp_path / "README.md").write_text("```bash\njobradar search --city 拉萨\n```", encoding="utf-8")
    result = release.documented_examples(documented_home, root=tmp_path)
    assert not result["ok"] and not result.get("skip")
    assert "0/1" in result["value"]
