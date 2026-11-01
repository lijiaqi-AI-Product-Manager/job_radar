import pytest

from jobradar.store.migrate import connect


@pytest.fixture(autouse=True)
def _query_clock(monkeypatch):
    """固定查询日期，避免带历史截止日的离线样本随测试运行日期改变含义。"""
    from jobradar.core import queries

    monkeypatch.setattr(queries, "now_ts", lambda: "2026-11-01T00:00:00Z")


@pytest.fixture
def jobs_db():
    conn = connect(":memory:", "jobs")
    yield conn
    conn.close()


@pytest.fixture
def text_db():
    conn = connect(":memory:", "text")
    yield conn
    conn.close()

@pytest.fixture(autouse=True)
def _offline_digests(monkeypatch):
    """单元测试绝不联网：提供占位摘要，由各下载测试注入自己的响应。"""
    from jobradar import local

    monkeypatch.setattr(local, "remote_digests", lambda timeout=6.0: {
        name + ".gz": "sha256:" + "f" * 64 for name in local.DB_FILES.values()})
