\set ON_ERROR_STOP on
-- A socket accepting connections is insufficient after a failed bootstrap.
SELECT index_id, source_release_id FROM knowledge_releases LIMIT 0;
SELECT index_id, chunk_id, embedding FROM knowledge_chunks LIMIT 0;
SELECT singleton, index_id FROM knowledge_active LIMIT 0;
SELECT 1 / CASE WHEN EXISTS (
  SELECT 1 FROM pg_constraint
  WHERE conrelid = 'knowledge_active'::regclass AND contype = 'f'
    AND confrelid = 'knowledge_releases'::regclass AND convalidated
    AND pg_get_constraintdef(oid) = 'FOREIGN KEY (index_id) REFERENCES knowledge_releases(index_id)'
) THEN 1 ELSE 0 END;
