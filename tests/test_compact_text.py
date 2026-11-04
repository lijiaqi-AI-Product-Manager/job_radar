"""精简正文保持完整内容、每岗位观测时间和查询语义；旧分发格式继续保留。"""

import hashlib
import sqlite3
from contextlib import closing

import pytest

from helpers import T, make_job
from jobradar.core import queries as q
from jobradar.pipeline.ingest import ingest_run, upsert_texts
from jobradar.store.migrate import connect
from jobradar.store.validate import validate_database


@pytest.fixture
def compact(tmp_path):
    from jobradar.compact_text import export_compact_text

    original = tmp_path / "plain.db"
    target = tmp_path / "compact.db"
    shared = "中文职责 PyTorch CUDA；百分比100% 和下划线_。" * 50
    rows = [make_job(1, description=shared, requirements=None),
            make_job(2, description=shared, requirements=None, text_observed_at=T(1)),
            make_job(3, description="", requirements="本科及以上"),
            make_job(4, description=None, requirements=None)]
    with closing(connect(original,"text",defer_search_index=True)) as text:
        upsert_texts(text,rows,ts=T(2))
        text.execute("INSERT INTO job_text VALUES (?,?,?,?)",("s1:4",None,None,T(2)))
        text.commit()
    before=hashlib.sha256(original.read_bytes()).hexdigest()
    export_compact_text(original,target)
    assert hashlib.sha256(original.read_bytes()).hexdigest()==before
    return original,target,rows


def test_lossless_export_preserves_null_empty_unicode_and_per_job_observation(compact):
    original,target,_=compact
    with closing(connect(original,"text",defer_search_index=True)) as a, closing(connect(target,"text")) as b:
        assert [tuple(r) for r in a.execute("SELECT * FROM job_text ORDER BY job_id")] == [
            tuple(r) for r in b.execute("SELECT * FROM job_text ORDER BY job_id")]
        assert b.execute("SELECT count(*) FROM jd_body").fetchone()[0]==3
        validate_database(b,"text")
        with pytest.raises(sqlite3.OperationalError):
            b.execute("DELETE FROM jd_ref")


@pytest.mark.parametrize("term",["PyTorch CUDA","100%","_","本科","不存在"])
def test_fulltext_and_detail_are_equivalent_with_both_storage_formats(compact,jobs_db,term):
    original,target,rows=compact
    ingest_run(jobs_db,"s1",rows,ts=T(2))
    with closing(connect(original,"text",defer_search_index=True)) as a, closing(connect(target,"text")) as b:
        ma,mb={},{}
        ra=q.search_jobs(jobs_db,text=term,text_conn=a,meta=ma)
        rb=q.search_jobs(jobs_db,text=term,text_conn=b,meta=mb)
        assert ra==rb and ma==mb
        assert q.get_job(jobs_db,a,"s1:1")==q.get_job(jobs_db,b,"s1:1")


def test_compact_export_rejects_unrecognized_source_without_replacing_old_file(tmp_path):
    from jobradar.compact_text import export_compact_text

    original,target=tmp_path/"bad.db",tmp_path/"previous.db"
    target.write_bytes(b"previous")
    with sqlite3.connect(original) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError):
        export_compact_text(original,target)
    assert target.read_bytes()==b"previous"


def test_corrupt_body_is_rejected_before_activation(compact):
    _,target,_=compact
    with sqlite3.connect(target) as conn:
        conn.execute("UPDATE jd_body SET payload=? WHERE id=1",(b"invalid zlib",))
    with closing(sqlite3.connect(target)) as conn, pytest.raises(ValueError,match="精简正文"):
        validate_database(conn,"text")


def test_compact_manifest_is_opt_in_for_new_downloads_and_stays_bound_to_base():
    import base64
    import json

    from jobradar import local
    files={name:{"sha256":"a"*64,"size":1,"asset":"a"*20+"-"+name} for name in
           ("jobs.db.gz","jd_text.db.gz","calendar.db.gz")}
    variant={"version":1,"sha256":"b"*64,"size":1,"asset":"b"*20+"-jd_text.compact.db.gz",
             "source_sha256":"a"*64}
    manifest={"version":1,"generation":"f"*20,"files":files,"variants":{"text_compact":variant}}
    def metadata():
        return {"body":"<!--jobradar-snapshot:"+base64.b64encode(json.dumps(manifest).encode()).decode()+"-->"}
    remote=local.snapshot_digests(metadata())
    assert remote["jd_text.db.gz"]=="sha256:"+"a"*64
    compact=local.select_text_storage(remote)
    assert compact["jd_text.db.gz"]=="sha256:"+"b"*64
    assert compact.asset_names["jd_text.db.gz"].endswith("-jd_text.compact.db.gz")
    assert local.select_text_storage(remote,compact=False)==remote
    variant["source_sha256"]="c"*64
    with pytest.raises(ValueError,match="清单"):
        local.snapshot_digests(metadata())
