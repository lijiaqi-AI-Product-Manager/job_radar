import json

import pytest

from helpers import T, make_job
from jobradar import cli, local
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    jobs = connect(tmp_path / "jobs.db", "jobs")
    text = connect(tmp_path / "jd_text.db", "text")
    js = [make_job(1, subcategory="算法", requirements="PyTorch"),
          make_job(2, source_id="s2", company="字节跳动", subcategory="算法", cities=["北京"])]
    ingest_run(jobs, "s1", js[:1], ts=now_ts())
    ingest_run(jobs, "s2", js[1:], ts=now_ts())
    upsert_texts(text, js, ts=now_ts())
    jobs.close()
    text.close()
    return tmp_path


def run(capsys, *argv):
    cli.main(list(argv))
    return json.loads(capsys.readouterr().out)


def test_search_envelope(home, capsys):
    out = run(capsys, "search", "--city", "北京")
    assert out["data_as_of"] and out["stale"] is False
    assert [r["company"] for r in out["results"]] == ["字节跳动"]


def test_show_found_and_missing(home, capsys):
    assert run(capsys, "show", "s1:1")["results"][0]["requirements"] == "PyTorch"
    out = run(capsys, "show", "nope")
    assert out["found"] is False and out["results"] == []


def test_compare_reports_not_found(home, capsys):
    out = run(capsys, "compare", "腾讯", "字节跳动", "某不存在公司", "--category", "算法")
    assert out["not_found"] == ["某不存在公司"]
    assert out["results"]["腾讯"][0]["requirements"] == "PyTorch"


def test_diff_and_sources(home, capsys):
    assert len(run(capsys, "diff", "--days", "1")["results"]) == 2
    out = run(capsys, "sources")
    assert out["failing"] == [] and {r["source_id"] for r in out["results"]} == {"s1", "s2"}


def test_stale_data_is_flagged(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    jobs = connect(tmp_path / "jobs.db", "jobs")
    ingest_run(jobs, "s1", [make_job(1)], ts=T(1))
    jobs.close()
    assert run(capsys, "search")["stale"] is True


def test_missing_data_tells_user_to_update(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    with pytest.raises(SystemExit, match="jobradar update"):
        cli.main(["search"])


def test_mirror_prefix(monkeypatch):
    monkeypatch.setenv("JOBRADAR_MIRROR", "https://mirror.example/")
    assert local.release_url("jobs.db").startswith("https://mirror.example/https://github.com/")


def _sqlite_bytes(tmp_path):
    p = tmp_path / "src.db"
    connect(p, "jobs").close()
    return p.read_bytes()


def test_download_public(tmp_path, monkeypatch):
    import httpx
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    body = _sqlite_bytes(tmp_path)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=body)

    cli._download("jobs.db", tmp_path / "jobs.db", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen == [local.release_url("jobs.db")]
    assert (tmp_path / "jobs.db").read_bytes() == body


def test_download_private_with_token(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    body = _sqlite_bytes(tmp_path)

    def handler(request):
        assert request.headers["authorization"] == "Bearer t0k"
        if request.url.path.endswith("/releases/tags/data-latest"):
            return httpx.Response(200, json={"assets": [{"name": "jobs.db", "url": "https://api.github.com/assets/7"}]})
        assert str(request.url) == "https://api.github.com/assets/7"
        assert request.headers["accept"] == "application/octet-stream"
        return httpx.Response(200, content=body)

    cli._download("jobs.db", tmp_path / "jobs.db", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert (tmp_path / "jobs.db").read_bytes() == body


def test_download_rejects_non_sqlite(tmp_path, monkeypatch):
    import httpx
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>not found</html>")))
    with pytest.raises(SystemExit, match="不是有效的数据库"):
        cli._download("jobs.db", tmp_path / "jobs.db", client=client)
    assert not (tmp_path / "jobs.db").exists()


def test_download_404_explains_private_repo(tmp_path, monkeypatch):
    import httpx
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(SystemExit, match="GITHUB_TOKEN"):
        cli._download("jobs.db", tmp_path / "jobs.db", client=client)


def test_sources_table_prints_status_columns(home, capsys):
    cli.main(["sources", "--table"])
    out = capsys.readouterr().out
    assert "None | None" not in out
    assert "s1" in out and "ok" in out


def test_trends_table(home, capsys):
    cli.main(["trends", "腾讯", "--table"])
    out = capsys.readouterr().out
    assert "None" not in out and "open" in out
