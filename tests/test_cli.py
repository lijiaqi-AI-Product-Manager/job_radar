import json
import sqlite3

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


def test_diff_by_category(home, capsys):
    """「最近哪类职位新增最多」：按职类聚合，而不是自己比对两次 search（评测 trend-02）。"""
    out = run(capsys, "diff", "--days", "7", "--by", "category")
    assert out["by"] == "category" and out["since"]
    assert out["results"] == [{"category": "技术", "n": 2}]


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


def test_download_aborts_slow_mirror_and_falls_back(tmp_path, no_token, monkeypatch):
    """read timeout 管不住"每秒滴几 KB"的连接（2026-10-22 Gitee 卡了 14 分钟），按吞吐兜底。"""
    import gzip

    import httpx
    body = _sqlite_bytes(tmp_path)
    clock = iter([0.0, 31.0] + [31.0] * 100)
    monkeypatch.setattr(cli, "_now", lambda: next(clock))

    def handler(request):
        url = str(request.url)
        if "github.com" in url:  # 慢镜像：30 秒只给 1KB，且文件有 27MB
            return httpx.Response(200, headers={"content-length": "27000000"}, content=iter([b"x" * 1024]))
        if url.endswith("/jobs.db.gz"):
            return httpx.Response(200, content=gzip.compress(body))
        return httpx.Response(404)

    used = cli._download("jobs.db", tmp_path / "jobs.db", client=_client(handler))
    assert used == "gitee"
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


def test_download_leaves_no_part_files(tmp_path, no_token):
    """404 分支要先关闭临时文件再删除：Windows 上删除打开中的文件会报 WinError 32。"""
    import httpx
    with pytest.raises(SystemExit):
        cli._download("jobs.db", tmp_path / "jobs.db", client=_client(lambda r: httpx.Response(404)))
    assert list(tmp_path.iterdir()) == []


def test_db_context_closes_connection(tmp_path, monkeypatch):
    """连接必须在退出时关闭：Windows 上未关闭的连接会锁住库，update 的原子替换会失败。"""
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    connect(tmp_path / "jobs.db", "jobs").close()
    with local.db("jobs") as conn:
        assert conn.execute("select count(*) from job").fetchone()[0] == 0
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("select 1")


class _FakeStdout:
    """模拟 Windows 上的 GBK 控制台：只记录 reconfigure 的参数。"""

    encoding = "gbk"

    def __init__(self, tty):
        self._tty = tty
        self.kwargs = {}

    def isatty(self):
        return self._tty

    def reconfigure(self, **kwargs):
        self.kwargs.update(kwargs)


def test_stdio_uses_utf8_for_pipes(monkeypatch):
    """管道输出（agent 读 JSON）统一 UTF-8，避免 GBK 把非常规字符替换成 ?。"""
    out, err = _FakeStdout(False), _FakeStdout(False)
    monkeypatch.setattr(cli.sys, "stdout", out)
    monkeypatch.setattr(cli.sys, "stderr", err)
    cli._configure_stdio()
    assert out.kwargs == {"encoding": "utf-8", "errors": "replace"}
    assert err.kwargs == {"encoding": "utf-8", "errors": "replace"}


def test_stdio_keeps_terminal_encoding(monkeypatch):
    """终端保留系统编码（中文正常显示），只把无法编码的字符降级，不再抛 UnicodeEncodeError。"""
    out = _FakeStdout(True)
    monkeypatch.setattr(cli.sys, "stdout", out)
    monkeypatch.setattr(cli.sys, "stderr", _FakeStdout(True))
    cli._configure_stdio()
    assert out.kwargs == {"errors": "replace"}


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.startswith("jobradar ")


def test_update_downloads_text_by_default(home, monkeypatch, capsys):
    got = []
    monkeypatch.setattr(cli, "_download", lambda name, dest, client=None, prefer=None: got.append(name) or "github")
    monkeypatch.setattr(cli, "_text_coverage", lambda *a, **k: None)  # 这个用例不测一致性检查
    cli.main(["update"])
    assert sorted(got) == ["calendar.db", "jd_text.db", "jobs.db"]  # 并行下载，完成顺序不保证
    got.clear()
    cli.main(["update", "--jobs-only", "--mirror", "gitee"])
    assert sorted(got) == ["calendar.db", "jobs.db"]


def test_update_downloads_in_parallel(home, monkeypatch, capsys):
    """三个库并行下载：jd_text 最大，串行时总耗时是三者之和（2026-10-22 实测 82s）。"""
    import threading
    barrier, done = threading.Barrier(3, timeout=5), []

    def fake(name, dest, client=None, prefer=None):
        barrier.wait()  # 三个下载必须同时在途
        done.append(name)
        return "github"

    monkeypatch.setattr(cli, "_download", fake)
    monkeypatch.setattr(cli, "_text_coverage", lambda *a, **k: None)  # 这个用例不测一致性检查
    cli.main(["update"])
    assert sorted(done) == ["calendar.db", "jd_text.db", "jobs.db"]


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
def test_text_coverage_detects_stale_jd_text(tmp_path):
    """镜像同步慢时 jobs 新、jd_text 旧，两个库 id 对不上——必须能测出来。"""
    import sqlite3
    jobs = sqlite3.connect(tmp_path / "jobs.db")
    jobs.execute("CREATE TABLE job(id TEXT, closed_at TEXT, last_seen TEXT)")
    jobs.executemany("INSERT INTO job VALUES (?,NULL,'2026-10-22T00:00:00Z')", [("a:1",), ("a:2",), ("a:3",), ("a:4",)])
    jobs.commit()
    jobs.close()
    text = sqlite3.connect(tmp_path / "jd_text.db")
    text.execute("CREATE TABLE job_text(job_id TEXT, description TEXT, requirements TEXT)")
    text.executemany("INSERT INTO job_text VALUES (?, 'd', '')", [("a:1",), ("a:2",)])
    text.commit()
    text.close()
    assert cli._text_coverage(tmp_path) == 0.5


def test_text_coverage_none_without_dbs(tmp_path):
    assert cli._text_coverage(tmp_path) is None
def test_doctor_reports_field_coverage_and_jd_match(home, capsys):
    """doctor 要告诉用户数据能不能用：字段覆盖率、JD 原文库是否对得上。"""
    cli.main(["doctor"])
    out = json.loads(capsys.readouterr().out)
    assert out["advice"]
    assert set(out["fields"]) >= {"cities", "campus_cities", "grad_year"}
    assert out["jd_text_match"] is not None

def test_sources_problems_shows_only_rejected_or_stale(home, capsys):
    """排障时只想看「没跑成功」的源：rejected 会一直挂着旧岗位，不能被淹没在几百个 ok 里。"""
    from datetime import UTC, datetime

    from helpers import make_job
    from jobradar.pipeline.ingest import ingest_run
    from jobradar.store.migrate import connect

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = home / "jobs.db"
    conn = connect(path, "jobs")
    ingest_run(conn, "s-ok", [make_job(1, source_id="s-ok")], ts=now)
    ingest_run(conn, "s-bad", [make_job(2, source_id="s-bad")], ts=now)
    ingest_run(conn, "s-bad", [], ts=now, ok=False, error="boom")   # 记为 failed
    conn.close()

    cli.main(["sources", "--problems"])
    out = json.loads(capsys.readouterr().out)
    assert [r["source_id"] for r in out["results"]] == ["s-bad"]

def test_update_skips_download_when_digest_unchanged(home, monkeypatch, capsys):
    """增量更新：Release 里 asset 的 sha256 没变就不下载那 20/35MB。"""
    import json as _json

    from jobradar import local
    from jobradar.store.migrate import connect

    for kind, name in (("jobs", "jobs.db"), ("text", "jd_text.db"), ("calendar", "calendar.db")):
        con = connect(home / name, kind)
        con.close()
    digests = {"jobs.db.gz": "d1", "jd_text.db.gz": "d2", "calendar.db.gz": "d3"}
    (home / ".sync.json").write_text(_json.dumps(digests), encoding="utf-8")
    monkeypatch.setattr(local, "remote_digests", lambda timeout=6.0: dict(digests))
    called = []
    monkeypatch.setattr(cli, "_download", lambda *a, **k: called.append(a) or "github")

    cli.main(["update"])
    out = _json.loads(capsys.readouterr().out)
    assert called == []                       # 一个都没下
    assert out["updated"] == [] and sorted(out["skipped"]) == ["calendar", "jobs", "text"]
