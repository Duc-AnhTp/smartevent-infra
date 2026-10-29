"""Publish one immutable, approved artifact/vector release atomically (offline job)."""

import argparse
from pathlib import Path
from smartevent_ai.adapters.outbound.knowledge.artifact_reader import (
    ArtifactKnowledgeStore,
)
from smartevent_ai.domain.knowledge import digest, fingerprint, eligible_chunks
from smartevent_ai.infrastructure.knowledge_config import SystemClock
from storage import connect, embeddings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--catalog-sha256", required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--release-sha256", required=True)
    args = parser.parse_args()
    catalog, artifact = args.catalog.read_bytes(), args.release.read_bytes()

    class Files:
        def artifacts(self):
            return catalog, args.catalog_sha256, artifact, args.release_sha256, 86400

    now = SystemClock().now()
    snapshot = ArtifactKnowledgeStore(Files()).snapshot(now)
    chunks = eligible_chunks(snapshot, now)
    if not chunks:
        raise ValueError("No approved public chunks to index")
    encoder = embeddings()
    profile = fingerprint(encoder.profile)
    rows = [(c.chunk_id, encoder.embed(c.context + c.text)) for c in chunks]
    index_id = fingerprint(
        {"artifact": digest(artifact), "catalog": digest(catalog), "embedding": profile}
    )
    with connect(writer=True) as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (index_id,)
        )
        connection.execute(
            "INSERT INTO knowledge_releases VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(index_id) DO NOTHING",
            (
                index_id,
                snapshot.release_id,
                catalog,
                digest(catalog),
                artifact,
                digest(artifact),
                profile,
                len(rows[0][1]),
            ),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO knowledge_chunks VALUES (%s,%s,%s::vector,%s) ON CONFLICT(index_id,chunk_id) DO NOTHING",
                [
                    (index_id, chunk_id, str(list(vector)), len(vector))
                    for chunk_id, vector in rows
                ],
            )
        connection.execute(
            "INSERT INTO knowledge_active VALUES (true,%s) ON CONFLICT(singleton) DO UPDATE SET index_id=EXCLUDED.index_id",
            (index_id,),
        )
    print(
        "Published",
        snapshot.release_id,
        "index",
        index_id,
        "public_chunks",
        len(rows),
        "profile",
        profile,
    )


if __name__ == "__main__":
    main()
