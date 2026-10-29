import os
import pytest
from fastapi import HTTPException
from service import fuse, require_token


def test_rrf_combines_rankings_with_deterministic_ties():
    assert fuse((["a", "b"], ["b", "c"])) == ["b", "a", "c"]
    assert fuse(([], [])) == []


def test_service_requires_configured_server_token(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "TEST_ONLY_" * 4)
    with pytest.raises(HTTPException):
        require_token(None)
    with pytest.raises(HTTPException):
        require_token("Bearer wrong")
    require_token("Bearer " + "TEST_ONLY_" * 4)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "")
    with pytest.raises(HTTPException):
        require_token("Bearer ")


@pytest.mark.skipif(
    not os.environ.get("KNOWLEDGE_TEST_HOST"),
    reason="requires isolated knowledge_test PostgreSQL/pgvector",
)
def test_reader_role_is_query_only_and_vector_extension_works():
    import psycopg

    assert os.environ.get("KNOWLEDGE_TEST_DATABASE") == "knowledge_test", (
        "Never run against business data"
    )
    with psycopg.connect(
        host=os.environ["KNOWLEDGE_TEST_HOST"],
        port=int(os.environ.get("KNOWLEDGE_TEST_PORT", "5433")),
        dbname="knowledge_test",
        user="knowledge_reader",
        password=os.environ["KNOWLEDGE_TEST_READER_PASSWORD"],
        connect_timeout=3,
    ) as connection:
        assert (
            connection.execute("SELECT '[1,0]'::vector <=> '[1,0]'::vector").fetchone()[
                0
            ]
            == 0
        )
        assert connection.execute(
            "SELECT has_table_privilege(current_user, 'knowledge_active', 'SELECT')"
        ).fetchone()[0]
        assert not connection.execute(
            "SELECT has_table_privilege(current_user, 'knowledge_active', 'UPDATE')"
        ).fetchone()[0]
        with pytest.raises(psycopg.DatabaseError):
            connection.execute("UPDATE knowledge_active SET singleton = true")
