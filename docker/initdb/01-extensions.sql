-- Runs once, on first initialisation of an empty data volume.
--
-- The pgvector image ships the extension binaries but does not enable it in any
-- database. Alembic also enables it before migrating, so this is belt and
-- braces: a psql session against a fresh volume already has vector available.
CREATE EXTENSION IF NOT EXISTS vector;
