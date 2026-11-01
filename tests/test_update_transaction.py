import sqlite3
from contextlib import closing

import pytest

from helpers import T, make_job
from jobradar import cli, local
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect


def seed(home):
    for kind, name in local.DB_FILES.items():
        with closing(connect(home / name, kind, defer_search_index=True)) as conn:
            if kind == "jobs":
                ingest_run(conn, "s1", [make_job(1)], ts=T(1))


def test_failed_required_download_never_changes_active_database_set(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    seed(tmp_path)
    before = {name: (tmp_path / name).read_bytes() for name in local.DB_FILES.values()}

    def download(name, destination, **kw):
        if name == "jd_text.db":
            raise SystemExit("正文摘要错误")
        if name == "jobs.db":
            with closing(connect(destination, "jobs", defer_search_index=True)) as conn:
                ingest_run(conn, "s1", [make_job(1), make_job(2)], ts=T(2))
        return "github"

    monkeypatch.setattr(cli, "_download", download)
    with pytest.raises(SystemExit):
        cli.main(["update", "--force"])
    assert all((tmp_path / name).read_bytes() == content for name, content in before.items())
    with local.db("jobs") as conn:
        assert conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 1


def test_successful_update_switches_all_files_and_preserves_legacy_copy(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    seed(tmp_path)

    def download(name, destination, **kw):
        if name == "jobs.db":
            with closing(connect(destination, "jobs", defer_search_index=True)) as conn:
                ingest_run(conn, "s1", [make_job(1), make_job(2)], ts=T(2))
        if name == "jd_text.db":
            with closing(connect(destination, "text", defer_search_index=True)) as conn:
                for i in (1, 2):
                    conn.execute("INSERT INTO job_text VALUES (?,?,?,?)", (f"s1:{i}", "有效职责正文", None, T(2)))
                conn.commit()
        return "github"

    monkeypatch.setattr(cli, "_download", download)
    cli.main(["update"])
    assert local.data_dir() != tmp_path
    with local.db("jobs") as conn:
        assert conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 2
    with closing(sqlite3.connect(tmp_path / "jobs.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 1


def test_bundle_reader_pins_one_generation_during_update(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    seed(tmp_path)
    with local.snapshot():
        original = local.data_dir()
        monkeypatch.setattr(local, "_active_directory", lambda: tmp_path / "new-generation")
        assert local.data_dir() == original
    assert local.data_dir() != original


def test_missing_remote_metadata_keeps_existing_files(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    seed(tmp_path)
    original = (tmp_path / "jobs.db").read_bytes()
    monkeypatch.setattr(local, "remote_digests", lambda: {})
    monkeypatch.setattr(cli, "_download", lambda *a, **kw: pytest.fail("没有完整性元数据时不能下载并覆盖"))
    with pytest.raises(SystemExit, match="完整性清单"):
        cli.main(["update", "--force"])
    assert (tmp_path / "jobs.db").read_bytes() == original


def test_failure_immediately_after_pointer_commit_never_deletes_active_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    seed(tmp_path)
    monkeypatch.setattr(cli, "_download", lambda *a, **kw: "github")
    activate = cli.activate

    def interrupted(directory):
        activate(directory)
        raise OSError("模拟提交后清理失败")

    monkeypatch.setattr(cli, "activate", interrupted)
    with pytest.raises(SystemExit, match="本地文件操作失败"):
        cli.main(["update", "--force", "--jobs-only"])
    assert local.data_dir().is_dir()
    with local.db("jobs") as conn:
        assert conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 1


def test_failed_pointer_replace_keeps_previous_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    seed(tmp_path)
    monkeypatch.setattr(cli, "_download", lambda *a, **kw: "github")

    def disk_failure(*args):
        raise OSError("模拟磁盘写入失败")

    monkeypatch.setattr(local.os, "replace", disk_failure)
    with pytest.raises(SystemExit, match="本地文件操作失败"):
        cli.main(["update", "--force", "--jobs-only"])
    assert local.data_dir() == tmp_path
    assert not (tmp_path / ".active.json").exists()
    with local.db("jobs") as conn:
        assert conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 1
