-- Runs automatically the first time the Postgres container starts
-- (files in /docker-entrypoint-initdb.d are executed on an empty data volume).

-- pgvector gives Postgres a `vector` column type and similarity operators.
-- LangChain's PGVector store creates its own tables on first use; it only needs
-- this extension to already exist.
CREATE EXTENSION IF NOT EXISTS vector;

-- Session memory: the running conversation, one row per turn.
-- This is the table the demo queries live to prove the app writes to the DB.
CREATE TABLE IF NOT EXISTS chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT        NOT NULL,
    role        TEXT        NOT NULL CHECK (role IN ('human', 'ai')),
    content     TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Reading a conversation always filters by session and orders by time.
CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, created_at);
