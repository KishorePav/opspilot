CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS evidence_chunks (
    chunk_id text PRIMARY KEY,
    document_id text NOT NULL,
    source text NOT NULL,
    title text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    content text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1536) NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(content, '')), 'B')
    ) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS evidence_chunks_embedding_hnsw_idx
    ON evidence_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS evidence_chunks_search_idx
    ON evidence_chunks USING gin (search_vector);

CREATE INDEX IF NOT EXISTS evidence_chunks_metadata_idx
    ON evidence_chunks USING gin (metadata jsonb_path_ops);
