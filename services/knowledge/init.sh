#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v reader_password="$KNOWLEDGE_READER_PASSWORD" \
  -v ingester_password="$KNOWLEDGE_INGESTER_PASSWORD" -f /opt/knowledge/schema.sql
