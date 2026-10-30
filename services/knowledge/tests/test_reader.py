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


def test_missing_evaluation_file_logs_warning_and_clear_degraded_status(
    monkeypatch, tmp_path, caplog
):
    import logging
    import service

    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("DENSE_FAILURE_POLICY", "bm25")
    missing_file = tmp_path / "nonexistent_evaluation.json"
    monkeypatch.setenv("RETRIEVAL_EVALUATION_PATH", str(missing_file))

    class Lexical:
        def rank(self, query, chunks, limit):
            return chunks[:limit]

    monkeypatch.setattr(service, "BM25Retriever", Lexical)
    retriever = HybridRetriever(object())
    with caplog.at_level(logging.WARNING):
        result = retriever.rank("query", ("chunk1",), 1)

    assert result == ("chunk1",)
    assert retriever.effective_mode == "degraded_bm25"
    assert retriever.fallback_reason == "DENSE_UNAVAILABLE"
    assert any(
        "degraded" in rec.message.lower() or "not found" in rec.message.lower()
        for rec in caplog.records
    )


def test_storage_connect_passes_configured_or_default_port(monkeypatch):
    import psycopg
    import storage

    captured = {}

    class DummyConn:
        read_only = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def dummy_connect(**kwargs):
        captured.update(kwargs)
        return DummyConn()

    monkeypatch.setattr(psycopg, "connect", dummy_connect)
    monkeypatch.setenv("PGHOST", "localhost")
    monkeypatch.setenv("PGDATABASE", "knowledge_test")
    monkeypatch.setenv("PGUSER", "reader")
    monkeypatch.setenv("PGPASSWORD", "secret")

    # 1. Default port 5432 when PGPORT unset
    monkeypatch.delenv("PGPORT", raising=False)
    with storage.connect():
        pass
    assert captured.get("port") == 5432

    # 2. Configured PGPORT
    monkeypatch.setenv("PGPORT", "5433")
    with storage.connect():
        pass
    assert captured.get("port") == 5433

    # 3. Configured INGEST_PGPORT for writer=True
    monkeypatch.setenv("INGEST_PGPORT", "5434")
    monkeypatch.setenv("INGEST_PGUSER", "ingester")
    monkeypatch.setenv("INGEST_PGPASSWORD", "secret_ingest")
    with storage.connect(writer=True):
        pass
    assert captured.get("port") == 5434


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
        res = connection.execute(
            "SELECT '[1,0]'::vector <=> '[1,0]'::vector"
        ).fetchone()
        assert res is not None and res[0] == 0
        priv_select = connection.execute(
            "SELECT has_table_privilege(current_user, 'knowledge_active', 'SELECT')"
        ).fetchone()
        assert priv_select is not None and priv_select[0]
        priv_update = connection.execute(
            "SELECT has_table_privilege(current_user, 'knowledge_active', 'UPDATE')"
        ).fetchone()
        assert priv_update is not None and not priv_update[0]
        with pytest.raises(psycopg.DatabaseError):
            connection.execute("UPDATE knowledge_active SET singleton = true")
