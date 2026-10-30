"""Knowledge-only database access; this service never receives business DB credentials."""

import os
from pathlib import Path
import json
from contextlib import contextmanager
from smartevent_ai.adapters.outbound.knowledge.embedding_adapter import (
    LocalOnnxEmbeddings,
)
from smartevent_ai.adapters.outbound.knowledge.tokenizer import LocalTokenizer
from smartevent_ai.domain.knowledge import digest, KnowledgeError


@contextmanager
def connect(writer=False):
    import psycopg

    prefix = "INGEST_" if writer else ""
    try:
        with psycopg.connect(
            host=os.environ["PGHOST"],
            dbname=os.environ["PGDATABASE"],
            user=os.environ[prefix + "PGUSER"],
            password=os.environ[prefix + "PGPASSWORD"],
            connect_timeout=3,
        ) as connection:
            connection.read_only = not writer
            yield connection
    except psycopg.Error as exc:
        raise KnowledgeError("Knowledge database unavailable") from exc


def embeddings():
    path = Path(os.environ["EMBEDDING_PROFILE_PATH"])
    raw = path.read_bytes()
    if digest(raw) != os.environ["EMBEDDING_PROFILE_SHA256"]:
        raise KnowledgeError("Embedding profile hash mismatch")
    profile = json.loads(raw)
    tokenizer = LocalTokenizer(
        Path(profile["tokenizer_path"]),
        profile["tokenizer_sha256"],
        profile["tokenizer_model_id"],
        profile["tokenizer_revision"],
        profile["context_window"],
    )
    return LocalOnnxEmbeddings(
        Path(profile["model_path"]),
        profile["model_sha256"],
        profile["model_id"],
        profile["revision"],
        tokenizer,
        profile["dimension"],
        profile.get("document_prefix", "passage: "),
        profile.get("query_prefix", "query: "),
    )


class DatabaseArtifacts:
    def __init__(self):
        self.release_id = None
        self.index_id = None
        self.embedding_profile = None

    def artifacts(self):
        with connect() as connection:
            connection.execute("SET LOCAL statement_timeout = '2500ms'")
            row = connection.execute(
                """SELECT r.index_id, r.source_release_id, r.catalog, r.catalog_sha256,
                r.artifact, r.release_sha256, r.embedding_profile FROM knowledge_active a
                JOIN knowledge_releases r ON r.index_id=a.index_id
                WHERE a.singleton AND r.catalog_sha256=%s AND r.release_sha256=%s""",
                (os.environ["CATALOG_SHA256"], os.environ["RELEASE_SHA256"]),
            ).fetchone()
        if row is None:
            raise KnowledgeError("No active release matching reviewed trust anchors")
        (
            self.index_id,
            self.release_id,
            catalog,
            catalog_hash,
            release,
            release_hash,
            self.embedding_profile,
        ) = row
        return bytes(catalog), catalog_hash, bytes(release), release_hash, 86400
