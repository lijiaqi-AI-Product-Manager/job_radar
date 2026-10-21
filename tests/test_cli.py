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
    assert local.asset_urls("jobs.db")[0] == ("mirror", "https://mirror.example/" + local.github_url("jobs.db"))


def test_asset_urls_order(monkeypatch):
    monkeypatch.delenv("JOBRADAR_MIRROR", raising=False)
    assert [m for m, _ in local.asset_urls("x")] == ["github", "gitee"]
    assert [m for m, _ in local.asset_urls("x", prefer="gitee")] == ["gitee", "github"]
    assert local.asset_urls("x", prefer="gitee")[0][1].startswith("https://gitee.com/")


def _sqlite_bytes(tmp_path):
    p = tmp_path / "src.db"
    connect(p, "jobs").close()
    return p.read_bytes()


@pytest.fixture
def no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("JOBRADAR_MIRROR", raising=False)


def _client(handler):
    import httpx
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_prefers_gzip(tmp_path, no_token):
    import gzip

    import httpx
    body = _sqlite_bytes(tmp_path)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=gzip.compress(body))

    used = cli._download("jobs.db", tmp_path / "jobs.db", client=_client(handler))
    assert used == "github" and seen == [local.github_url("jobs.db.gz")]
    assert (tmp_path / "jobs.db").read_bytes() == body


def test_download_falls_back_to_raw_then_next_mirror(tmp_path, no_token):
    import httpx
    body = _sqlite_bytes(tmp_path)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if "gitee.com" in str(request.url) and str(request.url).endswith("/jobs.db"):
            return httpx.Response(200, content=body)
        if "github.com" in str(request.url):
            raise httpx.ConnectError("blocked")
        return httpx.Response(404)

    used = cli._download("jobs.db", tmp_path / "jobs.db", client=_client(handler))
    assert used == "gitee"
    assert seen[-2:] == [local.gitee_url("jobs.db.gz"), local.gitee_url("jobs.db")]
    assert (tmp_path / "jobs.db").read_bytes() == body


def test_download_private_with_token(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    monkeypatch.delenv("JOBRADAR_MIRROR", raising=False)
    body = _sqlite_bytes(tmp_path)

    def handler(request):
        assert request.headers["authorization"] == "Bearer t0k"
        if request.url.path.endswith("/releases/tags/data-latest"):
            return httpx.Response(200, json={"assets": [{"name": "jobs.db", "url": "https://api.github.com/assets/7"}]})
        assert str(request.url) == "https://api.github.com/assets/7"
        assert request.headers["accept"] == "application/octet-stream"
        return httpx.Response(200, content=body)

    cli._download("jobs.db", tmp_path / "jobs.db", client=_client(handler))
    assert (tmp_path / "jobs.db").read_bytes() == body


def test_download_rejects_non_sqlite(tmp_path, no_token):
    import httpx
    client = _client(lambda r: httpx.Response(200, content=b"<html>not found</html>"))
    with pytest.raises(SystemExit, match="不是有效的数据库"):
        cli._download("jobs.db", tmp_path / "jobs.db", client=client)
    assert not (tmp_path / "jobs.db").exists()


def test_download_all_404_explains_private_repo(tmp_path, no_token):
    import httpx
    with pytest.raises(SystemExit, match="GITHUB_TOKEN"):
        cli._download("jobs.db", tmp_path / "jobs.db", client=_client(lambda r: httpx.Response(404)))


def test_update_downloads_text_by_default(home, monkeypatch, capsys):
    got = []
    monkeypatch.setattr(cli, "_download", lambda name, dest, client=None, prefer=None: got.append(name) or "github")
    cli.main(["update"])
    assert got == ["jobs.db", "jd_text.db", "calendar.db"]
    got.clear()
    cli.main(["update", "--jobs-only", "--mirror", "gitee"])
    assert got == ["jobs.db", "calendar.db"]


def test_update_tolerates_missing_calendar_db(home, monkeypatch, capsys):
    def fake(name, dest, client=None, prefer=None):
        if name == "calendar.db":
            raise SystemExit("404")
        return "github"
    monkeypatch.setattr(cli, "_download", fake)
    cli.main(["update"])
    assert json.loads(capsys.readouterr().out)["mirror"]["calendar"] is None


def test_sources_table_prints_status_columns(home, capsys):
    cli.main(["sources", "--table"])
    out = capsys.readouterr().out
    assert "None | None" not in out
    assert "s1" in out and "ok" in out


def test_trends_table(home, capsys):
    cli.main(["trends", "腾讯", "--table"])
    out = capsys.readouterr().out
    assert "None" not in out and "open" in out


def test_search_full_text(home, capsys):
    out = run(capsys, "search", "--text", "pytorch")
    assert [r["id"] for r in out["results"]] == ["s1:1"] and "PyTorch" in out["results"][0]["match"]


def test_search_full_text_without_text_db(home, capsys):
    (home / "jd_text.db").unlink()
    with pytest.raises(SystemExit):
        cli.main(["search", "--text", "pytorch"])


def test_calendar_build_query_and_stats(home, capsys, tmp_path):
    import yaml
    entries = tmp_path / "entries"
    entries.mkdir()
    (entries / "pdd.yaml").write_text(yaml.safe_dump({"group": "拼多多", "entries": [{
        "id": "pdd-2027-qz", "project_type": "秋招正式批", "grad_year": 2027, "as_of": "2026-10-21",
        "apply_url": "https://careers.pddglobalhr.com/campus/grad", "jd": {"status": "blocked"},
        "source": {"type": "official_site", "name": "拼多多校园招聘官网",
                   "url": "https://careers.pddglobalhr.com/campus/grad"},
    }]}, allow_unicode=True), encoding="utf-8")
    targets = tmp_path / "targets.yaml"
    targets.write_text(yaml.safe_dump({"sectors": {"互联网": ["拼多多", "腾讯", "字节跳动"]},
                                       "blocked": {"拼多多": "验证码"}}, allow_unicode=True), encoding="utf-8")
    cli.main(["calendar-build", "--jobs", str(home / "jobs.db"), "--out", str(home / "calendar.db"),
              "--entries", str(entries), "--targets", str(targets), "--sources", str(tmp_path / "nosources")])
    capsys.readouterr()

    out = run(capsys, "calendar", "--group", "拼多多")
    assert out["data_as_of"] and [r["id"] for r in out["results"]] == ["pdd-2027-qz"]
    assert out["results"][0]["hint"] == "拼多多希望你去他们的招聘页逛一逛哦~"
    auto = run(capsys, "calendar", "--group", "腾讯", "--origin", "auto")["results"]
    assert auto and auto[0]["jd_status"] == "linked"

    st = run(capsys, "stats")
    assert st["calendar"]["targets"] == 3 and st["calendar"]["calendar_covered"] == 3
    assert st["calendar"]["jd_covered"] == 2 and st["jobs"]["open_jobs"] == 2
    assert st["jobs"]["with_jd_text"] == 1


def test_calendar_without_db_tells_user_to_update(home, capsys):
    with pytest.raises(SystemExit, match="jobradar update"):
        cli.main(["calendar"])
