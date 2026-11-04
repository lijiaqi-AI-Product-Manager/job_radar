import base64
import hashlib
import json
import lzma
from contextlib import closing

import httpx
import pytest

from jobradar import compact_text, local, text_stream
from jobradar.cli import _install
from jobradar.store.migrate import connect


@pytest.fixture
def stream_source(tmp_path):
    plain, compact = tmp_path / 'plain.db', tmp_path / 'compact.db'
    rows = [('s:1', '职责\n中文\u0000🚀' * 30, None, '2026-11-01T01:02:03Z'),
            ('s:2', '职责\n中文\u0000🚀' * 30, None, '2026-11-02T01:02:03Z'),
            ('s:3', '', '本科及以上', '2026-11-03T01:02:03Z'),
            ('s:4', None, None, '2026-11-03T01:02:03Z')]
    with closing(connect(plain, 'text', defer_search_index=True)) as conn:
        conn.executemany('INSERT INTO job_text VALUES (?,?,?,?)', rows)
        conn.commit()
    compact_text.export_compact_text(plain, compact)
    return compact, rows


def _rows(path):
    with closing(connect(path, 'text', defer_search_index=True)) as conn:
        return [tuple(r) for r in conn.execute('SELECT * FROM job_text ORDER BY job_id')]


def test_stream_round_trip_retains_all_text_and_per_job_provenance(stream_source, tmp_path):
    source, rows = stream_source
    archive, target = tmp_path / 'text.xz', tmp_path / 'result.db'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    text_stream.export_text_stream(source, archive)
    text_stream.import_text_stream(archive, target)
    assert _rows(target) == rows
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    text_stream.verify_text_stream(source, archive)


def test_stream_export_is_deterministic(stream_source, tmp_path):
    source, _ = stream_source
    a, b = tmp_path / 'a.xz', tmp_path / 'b.xz'
    text_stream.export_text_stream(source, a)
    text_stream.export_text_stream(source, b)
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize('records', [
    [['wrong', 1, 0, 0], ['end', 0, 0]],
    [['jobradar-text-stream', 1, -1, 0]],
    [['jobradar-text-stream', 1, True, 0]],
    [['jobradar-text-stream', True, 0, 0], ['end', 0, 0]],
    [['jobradar-text-stream', 1, 1, 0], ['b', 1, [123, None]], ['end', 1, 0]],
    [['jobradar-text-stream', 1, 0, 1], ['r', 's:1', 99, '2026-11-01T00:00:00Z'], ['end', 0, 1]],
    [['jobradar-text-stream', 1, 1, 2], ['b', 1, [None, None]],
     ['r', 's:1', 1, '2026-11-01T00:00:00Z'], ['r', 's:1', 1, '2026-11-01T00:00:00Z'], ['end', 1, 2]],
    [['jobradar-text-stream', 1, 0, 0]],
    [['jobradar-text-stream', 1, 0, 0], ['end', 1, 0]],
    [['jobradar-text-stream', 1, 0, 0], ['end', 0, 0], ['extra']],
])
def test_invalid_stream_preserves_existing_target(tmp_path, records):
    archive, target = tmp_path / 'bad.xz', tmp_path / 'previous.db'
    archive.write_bytes(lzma.compress(b''.join(json.dumps(r).encode() + b'\n' for r in records), preset=3))
    target.write_bytes(b'previous')
    with pytest.raises(ValueError):
        text_stream.import_text_stream(archive, target)
    assert target.read_bytes() == b'previous'
    assert {p.name for p in tmp_path.iterdir()} == {'bad.xz', 'previous.db'}


@pytest.mark.parametrize('damage', ['truncated', 'checksum', 'concatenated'])
def test_xz_requires_complete_single_checked_stream(stream_source, tmp_path, damage):
    source, _ = stream_source
    archive = tmp_path / 'text.xz'
    text_stream.export_text_stream(source, archive)
    raw = archive.read_bytes()
    if damage == 'truncated':
        raw = raw[:-9]
    elif damage == 'checksum':
        raw = raw[:-20] + bytes([raw[-20] ^ 1]) + raw[-19:]
    else:
        raw += lzma.compress(b'extra')
    archive.write_bytes(raw)
    with pytest.raises(ValueError):
        text_stream.import_text_stream(archive, tmp_path / 'target.db')
    assert not (tmp_path / 'target.db').exists()


def test_stream_record_size_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(text_stream, 'MAX_STREAM_RECORD', 100)
    archive = tmp_path / 'big.xz'
    archive.write_bytes(lzma.compress(b'[' + b' ' * 200 + b']\n', preset=3))
    with pytest.raises(ValueError):
        text_stream.import_text_stream(archive, tmp_path / 'target.db')


def test_verified_wire_stream_installs_as_existing_compact_database(stream_source, tmp_path):
    source, rows = stream_source
    archive, target = tmp_path / 'text.xz', tmp_path / 'jd_text.db'
    text_stream.export_text_stream(source, archive)
    digest = 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()
    _install(archive, 'jd_text.db', True, target, digest, text_stream=True)
    assert _rows(target) == rows
    assert not archive.exists()


def test_stream_manifest_prefers_small_transfer_and_keeps_originals_for_old_clients():
    files = {name: {'sha256': 'a' * 64, 'size': 100, 'asset': 'a' * 20 + '-' + name}
             for name in ('jobs.db.gz', 'jd_text.db.gz', 'calendar.db.gz')}
    stream = {'version': 1, 'sha256': 'c' * 64, 'size': 50,
              'asset': 'c' * 20 + '-jd_text.rows.jsonl.xz', 'source_sha256': 'a' * 64}
    manifest = {'version': 1, 'generation': 'f' * 20, 'files': files, 'variants': {'text_stream': stream}}
    def metadata():
        return {'body': '<!--jobradar-snapshot:' + base64.b64encode(json.dumps(manifest).encode()).decode() + '-->'}
    remote = local.snapshot_digests(metadata())
    assert remote['jd_text.db.gz'] == 'sha256:' + 'a' * 64
    selected = local.select_text_storage(remote)
    assert selected['jd_text.db.gz'] == 'sha256:' + 'c' * 64
    assert selected.text_transport == 'stream'
    assert local.select_text_storage(remote, compact=False) is remote
    stream['source_sha256'] = 'd' * 64
    with pytest.raises(ValueError, match='清单'):
        local.snapshot_digests(metadata())


def test_real_download_path_selects_and_verifies_stream(stream_source, tmp_path, monkeypatch):
    from jobradar import cli
    source, rows = stream_source
    archive = tmp_path / 'text.xz'
    text_stream.export_text_stream(source, archive)
    raw = archive.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    remote = local.RemoteDigests({'jd_text.db.gz': 'sha256:' + sha},
        asset_names={'jd_text.db.gz': sha[:20] + '-jd_text.rows.jsonl.xz'}, text_transport='stream')
    monkeypatch.setattr(cli, 'asset_urls', lambda name, *a, **kw:
                        [('github', 'https://example.test/' + remote.asset_names.get(name, name))])
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=raw)
    verified = {}
    target = tmp_path / 'installed.db'
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert cli._download('jd_text.db', target, client, digests=remote, verified=verified) == 'github'
    assert _rows(target) == rows
    assert requests == ['https://example.test/' + remote.asset_names['jd_text.db.gz']]
    assert verified == {'jd_text.db.gz': 'sha256:' + sha}


def test_stream_does_not_overwrite_existing_database_on_checksum_failure(stream_source, tmp_path):
    source, rows = stream_source
    target = tmp_path / 'previous.db'
    target.write_bytes(source.read_bytes())
    archive = tmp_path / 'text.xz'
    text_stream.export_text_stream(source, archive)
    with pytest.raises(ValueError, match='摘要'):
        _install(archive, 'jd_text.db', True, target, 'sha256:' + '0' * 64, text_stream=True)
    assert _rows(target) == rows


def test_stream_decoder_enforces_memory_limit(stream_source, tmp_path, monkeypatch):
    source, _ = stream_source
    archive = tmp_path / 'text.xz'
    text_stream.export_text_stream(source, archive)
    monkeypatch.setattr(text_stream, 'STREAM_MEMORY', 1024)
    with pytest.raises(ValueError):
        text_stream.import_text_stream(archive, tmp_path / 'target.db')
