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
    """单元测试绝不联网：增量更新用的 GitHub digest 查询默认返回空（退化为全量）。"""
    from jobradar import local

    monkeypatch.setattr(local, "remote_digests", lambda timeout=6.0: {})
