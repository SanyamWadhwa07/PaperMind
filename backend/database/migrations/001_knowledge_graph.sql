-- Migration 001: Knowledge Graph — pgvector embeddings, citations, similarity
-- Run this after schema.sql and experience_schema.sql

-- Enable pgvector extension for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Add semantic embedding column to summaries (all-MiniLM-L6-v2 = 384 dims)
ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS embedding vector(384),
    ADD COLUMN IF NOT EXISTS abstract_text TEXT,
    ADD COLUMN IF NOT EXISTS primary_category VARCHAR(50);

-- ANN index for cosine similarity search (tune `lists` to ~sqrt(row_count))
CREATE INDEX IF NOT EXISTS idx_summaries_embedding
    ON summaries USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Paper citations extracted from reference sections
CREATE TABLE IF NOT EXISTS paper_citations (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_summary_id  UUID REFERENCES summaries(id) ON DELETE CASCADE,
    cited_arxiv_id     VARCHAR(50),
    cited_title        TEXT,
    cited_authors      TEXT[],
    year               INTEGER,
    citation_context   TEXT,   -- sentence where citation appears
    confidence         DECIMAL(5,4) DEFAULT 0.7,
    created_at         TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paper_citations_source  ON paper_citations(source_summary_id);
CREATE INDEX IF NOT EXISTS idx_paper_citations_cited   ON paper_citations(cited_arxiv_id);

-- Pre-computed top-K cosine similarity pairs (refreshed on each new paper)
CREATE TABLE IF NOT EXISTS paper_similarity (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_a_id       UUID REFERENCES summaries(id) ON DELETE CASCADE,
    paper_b_id       UUID REFERENCES summaries(id) ON DELETE CASCADE,
    similarity_score DECIMAL(6,5) NOT NULL,
    computed_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_a_id, paper_b_id)
);
CREATE INDEX IF NOT EXISTS idx_paper_similarity_a
    ON paper_similarity(paper_a_id, similarity_score DESC);
CREATE INDEX IF NOT EXISTS idx_paper_similarity_b
    ON paper_similarity(paper_b_id, similarity_score DESC);

-- Extend entity_relationships with temporal tracking and source papers
ALTER TABLE entity_relationships
    ADD COLUMN IF NOT EXISTS temporal_trend  JSONB,
    ADD COLUMN IF NOT EXISTS source_papers   UUID[];

-- Semantic similarity search: called by embedding_service.find_similar_papers
CREATE OR REPLACE FUNCTION match_papers(
    query_embedding  vector(384),
    p_user_id        UUID,
    match_count      INT DEFAULT 10,
    min_similarity   FLOAT DEFAULT 0.3
)
RETURNS TABLE(id UUID, paper_title TEXT, arxiv_id VARCHAR, similarity FLOAT)
LANGUAGE sql AS $$
    SELECT s.id,
           s.paper_title,
           s.arxiv_id,
           1 - (s.embedding <=> query_embedding) AS similarity
    FROM   summaries s
    WHERE  s.user_id = p_user_id
      AND  s.embedding IS NOT NULL
      AND  1 - (s.embedding <=> query_embedding) >= min_similarity
    ORDER  BY s.embedding <=> query_embedding
    LIMIT  match_count;
$$;

-- Duplicate detection: find existing papers with cosine similarity above threshold
CREATE OR REPLACE FUNCTION find_duplicate_papers(
    p_embedding  vector(384),
    p_user_id    UUID,
    p_threshold  FLOAT
)
RETURNS TABLE(id UUID, similarity FLOAT)
LANGUAGE sql AS $$
    SELECT s.id,
           1 - (s.embedding <=> p_embedding) AS similarity
    FROM   summaries s
    WHERE  s.user_id = p_user_id
      AND  s.embedding IS NOT NULL
      AND  1 - (s.embedding <=> p_embedding) > p_threshold
    ORDER  BY similarity DESC
    LIMIT  1;
$$;
