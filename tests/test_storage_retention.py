"""清理只处理本地已提交旧代；当前代、被读取的旧代与非快照文件不能删除。"""


import pytest

from jobradar import local
from jobradar.file_lock import file_lock


def generation(home,n):
    path=home/"snapshots"/f"{n:032x}"
    path.mkdir(parents=True)
    (path/"owned.txt").write_text("snapshot")
    return path


def test_default_keeps_one_generation_and_explicit_keep_retains_previous(tmp_path,monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME",str(tmp_path))
    one,two= generation(tmp_path,1),generation(tmp_path,2)
    local.activate(two,keep=1)
    assert two.exists() and not one.exists()
    three=generation(tmp_path,3)
    local.activate(three,keep=2)
    assert two.exists() and three.exists()
    assert local.storage_usage()["snapshot_count"]==2


def test_active_reader_prevents_pruning_until_it_finishes(tmp_path,monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME",str(tmp_path))
    one,two=generation(tmp_path,1),generation(tmp_path,2)
    with file_lock(one/".reader-test"):
        local.activate(two,keep=1)
        assert one.exists()
    local.prune_snapshots(keep=1)
    assert not one.exists() and two.exists()


@pytest.mark.parametrize("keep",[0,-1,True,11])
def test_invalid_retention_is_rejected_before_pointer_is_changed(tmp_path,monkeypatch,keep):
    monkeypatch.setenv("JOBRADAR_HOME",str(tmp_path))
    one=generation(tmp_path,1)
    with pytest.raises(ValueError):
        local.activate(one,keep=keep)
    assert not (tmp_path/".active.json").exists()


def test_unknown_directories_are_untouched(tmp_path,monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME",str(tmp_path))
    current=generation(tmp_path,1)
    unrelated=tmp_path/"snapshots"/"personal-files"
    unrelated.mkdir()
    local.activate(current,keep=1)
    assert unrelated.exists()


def test_staging_and_legacy_readers_are_protected(tmp_path,monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME",str(tmp_path))
    current=generation(tmp_path,1)
    staging=generation(tmp_path,2)
    (staging/".building").touch()
    (tmp_path/"jobs.db").write_bytes(b"legacy")
    (current/"jobs.db").write_bytes(b"active")
    with file_lock(tmp_path/".reader-test"):
        local.activate(current,keep=1)
        assert (tmp_path/"jobs.db").exists()
    local.prune_snapshots(keep=1)
    assert not (tmp_path/"jobs.db").exists()
    assert staging.exists()
