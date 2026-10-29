"""Fixed read-only policy endpoint. Ingest is a separate CLI, never an HTTP route."""

import json
import os
import secrets
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Query
from smartevent_ai.adapters.outbound.knowledge.artifact_reader import (
    ArtifactKnowledgeStore,
)
from smartevent_ai.adapters.outbound.knowledge.lexical_reader import BM25Retriever
from smartevent_ai.application.retrieve_policy import RetrievePolicy
from smartevent_ai.infrastructure.knowledge_config import SystemClock
from smartevent_ai.domain.knowledge import KnowledgeError, digest, fingerprint
from storage import DatabaseArtifacts, connect, embeddings

app = FastAPI(
    title="SmartEvent approved knowledge reader", docs_url=None, redoc_url=None
)


def require_token(authorization):
    expected = os.environ.get("KNOWLEDGE_SERVICE_TOKEN", "")
    if (
        len(expected) < 32
        or not authorization
        or not secrets.compare_digest(authorization, "Bearer " + expected)
    ):
        raise HTTPException(401, "Unauthorized")


@lru_cache(maxsize=1)
def encoder():
    return embeddings()


def fuse(rankings):
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, 1):
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
    return sorted(scores, key=lambda key: (-scores[key], key))


class HybridRetriever:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    def rank(self, query, chunks, limit):
        lexical = BM25Retriever().rank(query, chunks, max(limit, 5))
        mode = os.environ.get("RETRIEVAL_MODE", "bm25")
        if mode == "bm25":
            return lexical[:limit]
        if mode not in ("vector", "hybrid"):
            raise KnowledgeError("Unknown retrieval mode")
        # A pinned evaluation record is required before dense serving is selected.
        raw = Path(os.environ["RETRIEVAL_EVALUATION_PATH"]).read_bytes()
        record = json.loads(raw)
        if (
            digest(raw) != os.environ["RETRIEVAL_EVALUATION_SHA256"]
            or record.get("status") != "PASS"
            or record.get("release_id") != self.artifacts.release_id
            or record.get("embedding_profile") != self.artifacts.embedding_profile
            or record.get("mode") != mode
        ):
            raise KnowledgeError("Retrieval mode lacks matching evaluation evidence")
        embedder = encoder()
        if fingerprint(embedder.profile) != self.artifacts.embedding_profile:
            raise KnowledgeError("Embedding profile mismatch")
        vector = embedder.embed(query, query=True)
        allowed = {c.chunk_id: c for c in chunks}
        if not allowed:
            return ()
        threshold = record.get("minimum_similarity")
        if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise KnowledgeError("A calibrated abstention threshold is required")
        with connect() as connection:
            connection.execute("SET LOCAL statement_timeout = '2500ms'")
            rows = connection.execute(
                """SELECT chunk_id FROM knowledge_chunks
                WHERE index_id=%s AND chunk_id=ANY(%s) AND dimension=%s
                  AND 1-(embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector, chunk_id LIMIT 20""",
                (
                    self.artifacts.index_id,
                    list(allowed),
                    len(vector),
                    str(list(vector)),
                    threshold,
                    str(list(vector)),
                ),
            ).fetchall()
        dense = [row[0] for row in rows]
        ids = (
            dense if mode == "vector" else fuse(([c.chunk_id for c in lexical], dense))
        )
        return tuple(allowed[key] for key in ids[:limit])


@app.get("/health/ready")
def ready():
    try:
        artifacts = DatabaseArtifacts()
        store = ArtifactKnowledgeStore(artifacts)
        snapshot = store.snapshot(SystemClock().now())
        mode = os.environ.get("RETRIEVAL_MODE", "bm25")
        if mode != "bm25":
            # Validate the exact release/profile/evaluation and perform inference
            # before advertising a dense reader as ready.
            from smartevent_ai.domain.knowledge import eligible_chunks

            HybridRetriever(artifacts).rank(
                "kiểm tra truy xuất", eligible_chunks(snapshot, SystemClock().now()), 1
            )
        return {
            "status": "ready",
            "release_id": snapshot.release_id,
            "mode": os.environ.get("RETRIEVAL_MODE", "bm25"),
            "embedding_profile": artifacts.embedding_profile,
            "dense_serving_verified": mode != "bm25",
        }
    except Exception:
        raise HTTPException(503, "Knowledge unavailable") from None


@app.get("/v1/policy")
def policy(
    query: str = Query(min_length=1, max_length=2000),
    authorization: str | None = Header(default=None),
):
    require_token(authorization)
    try:
        artifacts = DatabaseArtifacts()
        store = ArtifactKnowledgeStore(artifacts)
        answer = RetrievePolicy(
            store, HybridRetriever(artifacts), SystemClock()
        ).answer(query)
        return asdict(answer)
    except Exception:
        raise HTTPException(503, "Knowledge unavailable") from None
