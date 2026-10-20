import pytest

from jobradar.store.migrate import connect


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
