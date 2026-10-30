"""Fixed read-only policy endpoint. Ingest is a separate CLI, never an HTTP route."""

import json
import logging
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

logger = logging.getLogger("knowledge.service")

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
        self.effective_mode = os.environ.get("RETRIEVAL_MODE", "bm25")
        self.fallback_reason = None

    def rank(self, query, chunks, limit):
        lexical = BM25Retriever().rank(query, chunks, max(limit, 5))
        mode = os.environ.get("RETRIEVAL_MODE", "bm25")
        self.effective_mode, self.fallback_reason = mode, None
        if mode == "bm25":
            return lexical[:limit]
        if mode not in ("vector", "hybrid"):
            raise KnowledgeError("Unknown retrieval mode")
        failure_policy = os.environ.get("DENSE_FAILURE_POLICY", "fail_closed")
        if failure_policy not in ("fail_closed", "bm25"):
            raise KnowledgeError("Unknown dense failure policy")
        try:
            result = self._dense_rank(query, chunks, limit, lexical, mode)
        except (KnowledgeError, OSError, ValueError, KeyError, TypeError) as exc:
            if failure_policy != "bm25":
                logger.error("Dense retrieval failed under fail_closed policy: %s", exc)
                raise KnowledgeError("Approved dense retrieval unavailable") from None
            self.effective_mode = "degraded_bm25"
            self.fallback_reason = "DENSE_UNAVAILABLE"
            logger.warning(
                "Dense retrieval unavailable (%s); degraded to bm25 fallback",
                exc,
            )
            return lexical[:limit]
        self.effective_mode = mode
        return result

    def _dense_rank(self, query, chunks, limit, lexical, mode):
        # A pinned evaluation record is required before dense serving is selected.
        eval_path_str = os.environ.get("RETRIEVAL_EVALUATION_PATH")
        if not eval_path_str:
            logger.warning(
                "RETRIEVAL_EVALUATION_PATH is not configured; dense retrieval disabled"
            )
            raise KnowledgeError("Retrieval evaluation path not configured")
        eval_path = Path(eval_path_str)
        if not eval_path.is_file():
            logger.warning(
                "Retrieval evaluation file not found at %s; operating in degraded mode",
                eval_path,
            )
            raise KnowledgeError(f"Retrieval evaluation file not found: {eval_path}")
        raw = eval_path.read_bytes()
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise KnowledgeError("Invalid retrieval evaluation record")
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
        if not isinstance(threshold, (int, float)) or not (0 <= threshold <= 1):
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
        retriever = HybridRetriever(artifacts)
        from smartevent_ai.domain.knowledge import eligible_chunks

        chunks = eligible_chunks(snapshot, SystemClock().now())
        if not chunks:
            raise KnowledgeError("No eligible knowledge chunks")
        if mode != "bm25":
            # Validate the exact release/profile/evaluation and perform inference
            # before advertising a dense reader as ready.
            retriever.rank("kiểm tra truy xuất", chunks, 1)
        if retriever.fallback_reason:
            logger.warning(
                "Knowledge reader ready in degraded status: mode=%s, fallback_reason=%s",
                retriever.effective_mode,
                retriever.fallback_reason,
            )
        return {
            "status": "degraded" if retriever.fallback_reason else "ready",
            "release_id": snapshot.release_id,
            "mode": retriever.effective_mode,
            "configured_mode": mode,
            "fallback_reason": retriever.fallback_reason,
            "embedding_profile": artifacts.embedding_profile,
            "dense_serving_verified": retriever.effective_mode in ("vector", "hybrid"),
        }
    except Exception as exc:
        logger.error("Knowledge service readiness check failed: %s", exc)
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
        retriever = HybridRetriever(artifacts)
        answer = RetrievePolicy(store, retriever, SystemClock()).answer(query)
        result = asdict(answer)
        if retriever.fallback_reason:
            result["mode"] = "degraded_bm25"
            logger.warning(
                "Policy served in degraded status: mode=%s, fallback_reason=%s",
                result["mode"],
                retriever.fallback_reason,
            )
        return result
    except Exception as exc:
        logger.error("Knowledge policy request failed: %s", exc)
        raise HTTPException(503, "Knowledge unavailable") from None
