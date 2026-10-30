-- For an old bootstrap that failed before creating reader/ingester roles.
-- psql -v ON_ERROR_STOP=1 -v reader_password=... -v ingester_password=... -f this.sql
BEGIN;
SELECT format('CREATE ROLE knowledge_reader LOGIN PASSWORD %L', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='knowledge_reader') \gexec
SELECT format('CREATE ROLE knowledge_ingester LOGIN PASSWORD %L', :'ingester_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='knowledge_ingester') \gexec
GRANT USAGE ON SCHEMA public TO knowledge_reader, knowledge_ingester;
GRANT SELECT ON knowledge_releases, knowledge_chunks TO knowledge_reader;
GRANT SELECT, INSERT, UPDATE ON knowledge_releases, knowledge_chunks TO knowledge_ingester;
ALTER ROLE knowledge_reader SET default_transaction_read_only=on;
COMMIT;
