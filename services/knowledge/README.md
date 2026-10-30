# Isolated knowledge service

This optional service has source implementation, not live acceptance approval. The default chat still uses the artifact BM25 reader and all business tools remain disabled.

## Start

Use `deploy/compose.demo.yml` plus `deploy/compose.knowledge.yml --profile knowledge`. Set separate bootstrap, reader, ingester passwords, a service token of at least 32 characters, model mount directory and reviewed catalog/release SHA-256 values in the deployment environment. The knowledge DB has no host port. Never reuse business Postgres credentials or volumes.

The reader receives only SELECT credentials. For an offline ingest job, run the same image with `/models` and approved artifact directory mounted read-only, PGHOST/PGDATABASE plus INGEST_PGUSER=knowledge_ingester and INGEST_PGPASSWORD supplied to that job alone:

```sh
python ingest.py --catalog /corpus/catalog.json --catalog-sha256 REVIEWED_HASH --release /corpus/release.json --release-sha256 REVIEWED_HASH
```

Do not add an ingest HTTP endpoint. The command validates production approvals, expiry, hashes and public audience using the existing artifact reader. It embeds only eligible chunks, writes an immutable index keyed by artifact/catalog/embedding hashes and switches the pointer in one transaction. Repeating an identical publish is idempotent. Changing embedding profiles does not overwrite an old index.

## Embedding profile

Mount a JSON profile with model_path/model_sha256/model_id/revision/dimension, tokenizer_path/tokenizer_sha256/tokenizer_model_id/tokenizer_revision/context_window and document_prefix/query_prefix. All paths are server-controlled inside /models. Set EMBEDDING_PROFILE_PATH and its SHA256. Model/tokenizer bytes are verified; no runtime downloads. A real Vietnamese model and independent evaluation must be selected before serving vector results.

BM25 is default. Vector/hybrid requires a pinned retrieval-evaluation.json and SHA256 containing status PASS, source release_id, embedding_profile fingerprint, mode vector/hybrid, and a calibrated minimum_similarity between 0 and 1. This is a deployment review record, not generated automatically by unit tests. Use the existing semantic benchmark to compare BM25/dense/RRF on the same release and independent question set. No approximate index is installed.

## AI integration

Set POLICY_BACKEND=http and fixed KNOWLEDGE_BASE_URL plus the server token. AI-side RAG-APPROVED-CORPUS and RAG-READONLY gates must both have reviewed PASS evidence; changing environment alone cannot bypass them. GET /v1/policy requires the bearer token. Knowledge reader returns only vetted extractive answers and citations, never raw catalog/SQL rows.

## Operations

Bootstrap now runs in one transaction and `knowledge_active.index_id` references
`knowledge_releases.index_id`. Database health checks validate all three tables
and the FK, rather than only testing whether PostgreSQL accepts connections.

For an older partially initialized **knowledge database**, take a backup first,
then run `migrations/000_repair_roles.sql` as its owner using psql with
`ON_ERROR_STOP=1`, `reader_password` and `ingester_password` variables from the
knowledge deployment credentials. This creates missing roles without changing
existing passwords. Next run `psql -v ON_ERROR_STOP=1 -f migrations/001_active_index.sql`.
The migration preserves existing releases/vectors and rejects unmapped legacy
pointer values. If no release table exists, use the corrected bootstrap on that
empty knowledge database. Restarting an existing Docker volume does not rerun init.
Do not remove business database volumes to repair knowledge initialization.

`DENSE_FAILURE_POLICY=fail_closed` is the default: missing/mismatched evaluation
or unavailable dense inference returns 503. Explicit `bm25` permits lexical
fallback and reports `degraded_bm25`, with `dense_serving_verified=false` in health.
Neither policy permits running an unapproved dense model. AI preserves the
degraded response mode. Restore normal mode only with matching evaluation evidence.

The knowledge CI uses a disposable `knowledge_test` PostgreSQL/pgvector database,
tests the canonical DDL, legacy pointer migration, FK rejection and reader privileges.
Those storage fixtures are not approved serving corpora or model quality evidence.

Back up only the knowledge database with pg_dump using an operator account; restore to a separate knowledge database, verify artifact/profile hashes and reader privileges, then point the reader to it. No commands remove business volumes. Roll back by switching knowledge_active to an existing index_id transactionally and deploy its matching catalog/release trust anchors. Revoke/expire a source through a newly reviewed catalog publication; mismatched or stale anchors fail closed rather than serving cached evidence. Do not extend approvals just to make readiness pass.

Cold-start readiness, query-only privileges, expiry/revocation, restart/restore and real vector recall require PostgreSQL/Docker integration. The compose profile alone is not evidence these checks passed. The service driver is version-pinned; a platform-specific hash lock and image digest pin remain release prerequisites.
