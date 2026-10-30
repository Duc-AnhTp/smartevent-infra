import os
import pytest
from fastapi import HTTPException
from service import fuse, require_token, HybridRetriever
from smartevent_ai.domain.knowledge import KnowledgeError


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


@pytest.mark.parametrize("failure_policy", ["fail_closed", "bm25"])
def test_missing_dense_evaluation_obeys_explicit_policy(
    monkeypatch, tmp_path, failure_policy
):
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("DENSE_FAILURE_POLICY", failure_policy)
    monkeypatch.setenv("RETRIEVAL_EVALUATION_PATH", str(tmp_path / "missing.json"))
    import service

    class Lexical:
        def rank(self, query, chunks, limit):
            return chunks[:limit]

    monkeypatch.setattr(service, "BM25Retriever", Lexical)
    monkeypatch.setattr(
        service, "encoder", lambda: pytest.fail("unapproved dense model must not run")
    )
    retriever = HybridRetriever(object())
    if failure_policy == "fail_closed":
        with pytest.raises(KnowledgeError):
            retriever.rank("test", ("chunk",), 1)
    else:
        assert retriever.rank("test", ("chunk",), 1) == ("chunk",)
        assert retriever.effective_mode == "degraded_bm25"
        assert retriever.fallback_reason == "DENSE_UNAVAILABLE"


def test_invalid_dense_failure_policy_never_silently_falls_back(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("DENSE_FAILURE_POLICY", "allow_everything")
    with pytest.raises(KnowledgeError):
        HybridRetriever(object()).rank("test", (), 1)


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
