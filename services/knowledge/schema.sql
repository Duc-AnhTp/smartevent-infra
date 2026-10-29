CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE knowledge_releases (
  index_id text PRIMARY KEY,
  source_release_id text NOT NULL,
  catalog bytea NOT NULL CHECK (octet_length(catalog) <= 524288),
  catalog_sha256 text NOT NULL CHECK (length(catalog_sha256) = 64),
  artifact bytea NOT NULL CHECK (octet_length(artifact) <= 16000000),
  release_sha256 text NOT NULL CHECK (length(release_sha256) = 64),
  embedding_profile text NOT NULL,
  dimension integer NOT NULL CHECK (dimension BETWEEN 1 AND 4096)
);
CREATE TABLE knowledge_chunks (
  index_id text NOT NULL REFERENCES knowledge_releases(index_id),
  chunk_id text NOT NULL,
  embedding vector NOT NULL,
  dimension integer NOT NULL,
  PRIMARY KEY(index_id, chunk_id),
  CHECK (vector_dims(embedding) = dimension)
);
CREATE TABLE knowledge_active (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  release_id text NOT NULL REFERENCES knowledge_releases(release_id)
);
-- Exact vector search first: no approximate index before recall/latency evaluation.
CREATE ROLE knowledge_reader LOGIN PASSWORD :'reader_password';
CREATE ROLE knowledge_ingester LOGIN PASSWORD :'ingester_password';
GRANT USAGE ON SCHEMA public TO knowledge_reader, knowledge_ingester;
GRANT SELECT ON knowledge_releases, knowledge_chunks, knowledge_active TO knowledge_reader;
ALTER ROLE knowledge_reader SET default_transaction_read_only = on;
GRANT SELECT, INSERT, UPDATE ON knowledge_releases, knowledge_chunks, knowledge_active TO knowledge_ingester;
