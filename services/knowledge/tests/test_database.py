"""Real PostgreSQL/pgvector contract. Run only against a disposable knowledge_test DB."""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("KNOWLEDGE_TEST_ADMIN_DSN"),
    reason="requires isolated knowledge_test database",
)


def test_publish_pointer_migration_vector_and_reader_permissions():
    import psycopg

    with psycopg.connect(
        os.environ["KNOWLEDGE_TEST_ADMIN_DSN"], autocommit=True
    ) as connection:
        assert connection.info.dbname == "knowledge_test", (
            "Never run this fixture on business data"
        )
        index_id = "TEST_ONLY_INDEX"
        connection.execute(
            "INSERT INTO knowledge_releases VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                index_id,
                "TEST_ONLY_SOURCE",
                b"{}",
                "0" * 64,
                b"{}",
                "1" * 64,
                "TEST_ONLY_PROFILE",
                2,
            ),
        )
        connection.execute(
            "INSERT INTO knowledge_chunks VALUES (%s,%s,'[1,0]'::vector,2) ON CONFLICT DO NOTHING",
            (index_id, "TEST_ONLY_CHUNK"),
        )
        connection.execute(
            "INSERT INTO knowledge_active VALUES (true,%s) ON CONFLICT(singleton) DO UPDATE SET index_id=EXCLUDED.index_id",
            (index_id,),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute("UPDATE knowledge_active SET index_id='MISSING_INDEX'")
        assert (
            connection.execute("SELECT index_id FROM knowledge_active").fetchone()[0]
            == index_id
        )
        # Simulate the old column name on an isolated fixture, then migrate twice.
        connection.execute(
            "ALTER TABLE knowledge_active RENAME COLUMN index_id TO release_id"
        )
        migration = (
            Path(__file__).resolve().parents[1] / "migrations/001_active_index.sql"
        )
        for _ in range(2):
            connection.execute(migration.read_text(encoding="utf-8"), prepare=False)
        assert (
            connection.execute("SELECT index_id FROM knowledge_active").fetchone()[0]
            == index_id
        )

    with psycopg.connect(
        host=os.environ["KNOWLEDGE_TEST_HOST"],
        port=int(os.environ.get("KNOWLEDGE_TEST_PORT", "5433")),
        dbname="knowledge_test",
        user="knowledge_reader",
        password=os.environ["KNOWLEDGE_TEST_READER_PASSWORD"],
        autocommit=True,
    ) as reader:
        assert (
            reader.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        )
        assert (
            reader.execute(
                "SELECT '[1,0]'::vector <=> embedding FROM knowledge_chunks WHERE chunk_id='TEST_ONLY_CHUNK'"
            ).fetchone()[0]
            == 0
        )
        assert (
            reader.execute("SELECT index_id FROM knowledge_active").fetchone()[0]
            == index_id
        )
        with pytest.raises(psycopg.DatabaseError):
            reader.execute("UPDATE knowledge_active SET singleton=true")
