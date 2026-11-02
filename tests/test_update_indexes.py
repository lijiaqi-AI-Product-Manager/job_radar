import json
import shutil
import sqlite3

import pytest

from helpers import make_job
from jobradar import cli, local
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts


@pytest.fixture
def snapshot_files(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    remote.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("JOBRADAR_HOME", str(home))
    rows = [make_job(1, description="PyTorch CUDA"), make_job(2)]
    for kind, name in local.DB_FILES.items():
        with connect(remote / name, kind, defer_search_index=True) as conn:
            if kind == "jobs":
                ingest_run(conn, "s1", rows, ts=now_ts())
            elif kind == "text":
                upsert_texts(conn, rows, ts=now_ts())

    def download(name, dest, **kwargs):
        shutil.copyfile(remote / name, dest)
        return "fixture"

    monkeypatch.setattr(cli, "_download", download)
    return home


@pytest.mark.parametrize("no_index", [False, True])
def test_update_prepares_search_before_activation_and_can_opt_out(snapshot_files, capsys, no_index):
    cli.main(["update", "--force"] + (["--no-index"] if no_index else ["--prepare-index"]))
    json.loads(capsys.readouterr().out)
    directory = local.data_dir()
    for name, expected in [("jobs.db", 2 if no_index else 3), ("jd_text.db", 1 if no_index else 2)]:
        with sqlite3.connect(directory / name) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == expected


def test_index_failure_cannot_activate_partial_snapshot(snapshot_files, monkeypatch):
    def failed(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(cli, "_prepare_indexes", failed, raising=False)
    with pytest.raises(SystemExit):
        cli.main(["update", "--force", "--prepare-index"])
    assert not (snapshot_files / ".active.json").exists()
    assert list((snapshot_files / "snapshots").iterdir()) == []


def test_unchanged_compatible_snapshot_prepares_once_without_redownloading(
    snapshot_files, monkeypatch, capsys
):
    for name in local.DB_FILES.values():
        shutil.copyfile(snapshot_files.parent / "remote" / name, snapshot_files / name)
    values = {name + ".gz": "sha256:" + "f" * 64 for name in local.DB_FILES.values()}
    local.save_sync_meta({"_verified_assets": values})

    def unexpected(*args, **kwargs):
        raise AssertionError("unchanged files must not be downloaded")

    monkeypatch.setattr(cli, "_download", unexpected)
    cli.main(["update", "--prepare-index"])
    first = json.loads(capsys.readouterr().out)
    assert first["updated"] == []
    assert set(first["indexes_prepared"]) == {"jobs", "text"}
    generation = local.data_dir()
    cli.main(["update", "--prepare-index"])
    second = json.loads(capsys.readouterr().out)
    assert second["updated"] == []
    assert local.data_dir() == generation
