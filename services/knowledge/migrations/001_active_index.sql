-- Run as the knowledge database owner, with psql -v ON_ERROR_STOP=1.
-- Repairs a partial older bootstrap without dropping stored releases or vectors.
BEGIN;
DO $$
BEGIN
  IF to_regclass('public.knowledge_releases') IS NULL THEN
    RAISE EXCEPTION 'Missing knowledge_releases: run the corrected bootstrap on this empty knowledge database';
  END IF;
  IF to_regclass('public.knowledge_active') IS NOT NULL
     AND EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='knowledge_active' AND column_name='release_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='knowledge_active' AND column_name='index_id') THEN
      RAISE EXCEPTION 'Both release_id and index_id exist: explicit data reconciliation required';
    END IF;
    ALTER TABLE knowledge_active RENAME COLUMN release_id TO index_id;
  END IF;
END $$;
CREATE TABLE IF NOT EXISTS knowledge_active (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  index_id text NOT NULL
);
-- Unmapped legacy source release IDs fail validation and roll back the transaction.
-- Do not guess an index when several embedding profiles exist for a release.
ALTER TABLE knowledge_active DROP CONSTRAINT IF EXISTS knowledge_active_release_id_fkey;
ALTER TABLE knowledge_active DROP CONSTRAINT IF EXISTS knowledge_active_index_id_fkey;
ALTER TABLE knowledge_active ADD CONSTRAINT knowledge_active_index_id_fkey
  FOREIGN KEY (index_id) REFERENCES knowledge_releases(index_id);
GRANT SELECT ON knowledge_active TO knowledge_reader;
GRANT SELECT, INSERT, UPDATE ON knowledge_active TO knowledge_ingester;
COMMIT;
