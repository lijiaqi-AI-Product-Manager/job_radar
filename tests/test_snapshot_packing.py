import random
import sqlite3
import string
from contextlib import closing

import pytest

from helpers import T, make_job
from jobradar.compact_text import export_compact_text
from jobradar.pipeline.ingest import upsert_texts
from jobradar.store.migrate import connect
from jobradar.text_stream import export_text_stream, import_text_stream


@pytest.mark.parametrize("count", [100, 3000])
def test_packed_text_retains_all_records_while_avoiding_overflow_page_waste(tmp_path, count):
    plain, compact = tmp_path / "plain.db", tmp_path / "compact.db"
    generator = random.Random(17)
    rows = [make_job(index, description="".join(generator.choices(string.ascii_letters + string.digits, k=2200)))
            for index in range(count)]
    with closing(connect(plain, "text", defer_search_index=True)) as text:
        upsert_texts(text, rows, ts=T(2))
    export_compact_text(plain, compact)
    reference = tmp_path / "small-pages.db"
    with sqlite3.connect(compact.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA page_size=4096")
        conn.execute("VACUUM INTO ?", (str(reference),))
    assert compact.stat().st_size <= reference.stat().st_size
    if count == 3000:
        assert compact.stat().st_size < reference.stat().st_size
    archive, imported = tmp_path / "text.xz", tmp_path / "imported.db"
    export_text_stream(compact, archive)
    import_text_stream(archive, imported)
    assert imported.stat().st_size <= reference.stat().st_size
    with closing(connect(plain, "text", defer_search_index=True)) as original:
        expected = [tuple(r) for r in original.execute("SELECT * FROM job_text ORDER BY job_id")]
    for path in (compact, imported):
        with closing(connect(path, "text")) as actual:
            assert [tuple(r) for r in actual.execute("SELECT * FROM job_text ORDER BY job_id")] == expected
