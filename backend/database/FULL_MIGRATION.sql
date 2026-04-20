-- ============================================================
-- PaperMind Full Database Migration
-- Run this once in Supabase Dashboard → SQL Editor
-- ============================================================

-- ─── 1. EXTENSIONS ───────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ─── 2. CORE TABLES (schema.sql) ─────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    bio TEXT,
    avatar_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS summaries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    paper_title TEXT NOT NULL,
    paper_authors TEXT[],
    paper_url TEXT,
    arxiv_id VARCHAR(50),
    summary_data JSONB NOT NULL,
    model_used VARCHAR(100) DEFAULT 'LED',
    processing_time_seconds DECIMAL(10, 2),
    word_count INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    search_vector tsvector
);

CREATE TABLE IF NOT EXISTS user_activity (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    activity_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_summaries_user_id ON summaries(user_id);
CREATE INDEX IF NOT EXISTS idx_summaries_created_at ON summaries(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_arxiv_id ON summaries(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_user_activity_user_id ON user_activity(user_id);
CREATE INDEX IF NOT EXISTS idx_user_activity_created_at ON user_activity(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_search ON summaries USING GIN(search_vector);

-- Trigger functions
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION summaries_search_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.paper_title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(array_to_string(NEW.paper_authors, ' '), '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS summaries_search_trigger ON summaries;
CREATE TRIGGER summaries_search_trigger
    BEFORE INSERT OR UPDATE ON summaries
    FOR EACH ROW EXECUTE FUNCTION summaries_search_update();

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_summaries_updated_at ON summaries;
CREATE TRIGGER update_summaries_updated_at
    BEFORE UPDATE ON summaries
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ─── 3. DISABLE RLS (app uses its own JWT, not Supabase Auth) ─
ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE summaries DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_activity DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS summaries_user_policy ON summaries;
DROP POLICY IF EXISTS activity_user_policy ON user_activity;

-- ─── 4. EXPERIENCE / AGENT TABLES (experience_schema.sql) ────

CREATE TABLE IF NOT EXISTS entity_knowledge (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    frequency_count INTEGER DEFAULT 1,
    confidence_score DECIMAL(5, 4) DEFAULT 0.5,
    typical_contexts JSONB,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    validated_by_agents TEXT[],
    metadata JSONB,
    UNIQUE(entity_name, entity_type)
);

CREATE TABLE IF NOT EXISTS pattern_performance (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pattern_id VARCHAR(100) NOT NULL,
    pattern_type VARCHAR(50) NOT NULL,
    total_attempts INTEGER DEFAULT 0,
    successful_extractions INTEGER DEFAULT 0,
    false_positives INTEGER DEFAULT 0,
    precision_score DECIMAL(5, 4),
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    performance_by_domain JSONB,
    UNIQUE(pattern_id, pattern_type)
);

CREATE TABLE IF NOT EXISTS section_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain VARCHAR(50),
    section_sequence TEXT[],
    frequency_count INTEGER DEFAULT 1,
    confidence_score DECIMAL(5, 4) DEFAULT 0.5,
    average_section_lengths JSONB,
    typical_subsections JSONB,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS result_baselines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_name VARCHAR(255) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(255),
    min_value DECIMAL(10, 4),
    max_value DECIMAL(10, 4),
    mean_value DECIMAL(10, 4),
    std_dev DECIMAL(10, 4),
    sample_count INTEGER DEFAULT 1,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    outlier_threshold_low DECIMAL(10, 4),
    outlier_threshold_high DECIMAL(10, 4),
    UNIQUE(dataset_name, metric_name, model_name)
);

CREATE TABLE IF NOT EXISTS agent_execution_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID,
    agent_name VARCHAR(100) NOT NULL,
    execution_time_ms INTEGER,
    status VARCHAR(50),
    items_extracted INTEGER,
    confidence_avg DECIMAL(5, 4),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_consensus_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID,
    extraction_type VARCHAR(100),
    extracted_value TEXT,
    agents_voting JSONB,
    consensus_reached BOOLEAN,
    final_confidence DECIMAL(5, 4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entity_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_1 VARCHAR(255) NOT NULL,
    entity_1_type VARCHAR(50) NOT NULL,
    entity_2 VARCHAR(255) NOT NULL,
    entity_2_type VARCHAR(50) NOT NULL,
    relationship_type VARCHAR(50),
    frequency_count INTEGER DEFAULT 1,
    confidence_score DECIMAL(5, 4) DEFAULT 0.5,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_1, entity_1_type, entity_2, entity_2_type, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_entity_knowledge_type ON entity_knowledge(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_knowledge_name ON entity_knowledge(entity_name);
CREATE INDEX IF NOT EXISTS idx_entity_knowledge_confidence ON entity_knowledge(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_pattern_performance_type ON pattern_performance(pattern_type);
CREATE INDEX IF NOT EXISTS idx_section_templates_domain ON section_templates(domain);
CREATE INDEX IF NOT EXISTS idx_result_baselines_dataset ON result_baselines(dataset_name);
CREATE INDEX IF NOT EXISTS idx_result_baselines_metric ON result_baselines(metric_name);
CREATE INDEX IF NOT EXISTS idx_agent_execution_log_agent ON agent_execution_log(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_execution_log_created ON agent_execution_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_relationships_e1 ON entity_relationships(entity_1, entity_1_type);
CREATE INDEX IF NOT EXISTS idx_entity_relationships_e2 ON entity_relationships(entity_2, entity_2_type);

-- ─── 5. MIGRATION 001: Knowledge Graph ───────────────────────

ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS embedding vector(384),
    ADD COLUMN IF NOT EXISTS abstract_text TEXT,
    ADD COLUMN IF NOT EXISTS primary_category VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_summaries_embedding
    ON summaries USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE TABLE IF NOT EXISTS paper_citations (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_summary_id  UUID REFERENCES summaries(id) ON DELETE CASCADE,
    cited_arxiv_id     VARCHAR(50),
    cited_title        TEXT,
    cited_authors      TEXT[],
    year               INTEGER,
    citation_context   TEXT,
    confidence         DECIMAL(5,4) DEFAULT 0.7,
    created_at         TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paper_citations_source ON paper_citations(source_summary_id);
CREATE INDEX IF NOT EXISTS idx_paper_citations_cited  ON paper_citations(cited_arxiv_id);

CREATE TABLE IF NOT EXISTS paper_similarity (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_a_id       UUID REFERENCES summaries(id) ON DELETE CASCADE,
    paper_b_id       UUID REFERENCES summaries(id) ON DELETE CASCADE,
    similarity_score DECIMAL(6,5) NOT NULL,
    computed_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_a_id, paper_b_id)
);
CREATE INDEX IF NOT EXISTS idx_paper_similarity_a ON paper_similarity(paper_a_id, similarity_score DESC);
CREATE INDEX IF NOT EXISTS idx_paper_similarity_b ON paper_similarity(paper_b_id, similarity_score DESC);

ALTER TABLE entity_relationships
    ADD COLUMN IF NOT EXISTS temporal_trend JSONB,
    ADD COLUMN IF NOT EXISTS source_papers  UUID[];

CREATE OR REPLACE FUNCTION match_papers(
    query_embedding  vector(384),
    p_user_id        UUID,
    match_count      INT DEFAULT 10,
    min_similarity   FLOAT DEFAULT 0.3
)
RETURNS TABLE(id UUID, paper_title TEXT, arxiv_id VARCHAR, similarity FLOAT)
LANGUAGE sql AS $$
    SELECT s.id, s.paper_title, s.arxiv_id,
           1 - (s.embedding <=> query_embedding) AS similarity
    FROM   summaries s
    WHERE  s.user_id = p_user_id
      AND  s.embedding IS NOT NULL
      AND  1 - (s.embedding <=> query_embedding) >= min_similarity
    ORDER  BY s.embedding <=> query_embedding
    LIMIT  match_count;
$$;

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

-- ─── 6. MIGRATION 002: Quality Score ─────────────────────────

ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS quality_score DECIMAL(5,4);

CREATE INDEX IF NOT EXISTS idx_summaries_quality
    ON summaries(quality_score DESC)
    WHERE quality_score IS NOT NULL;

-- ─── 7. MIGRATION 003: User Feedback ─────────────────────────

CREATE TABLE IF NOT EXISTS summary_feedback (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    summary_id    UUID REFERENCES summaries(id) ON DELETE CASCADE,
    user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
    rating        INTEGER CHECK (rating BETWEEN 1 AND 5),
    feedback_type VARCHAR(50) DEFAULT 'rating',
    comment       TEXT,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(summary_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_summary ON summary_feedback(summary_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user    ON summary_feedback(user_id);

-- ─── 8. MIGRATION 004: Collections ───────────────────────────

CREATE TABLE IF NOT EXISTS collections (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    color       VARCHAR(7) DEFAULT '#6366f1',
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_collections_user ON collections(user_id);

CREATE TABLE IF NOT EXISTS collection_papers (
    collection_id UUID REFERENCES collections(id) ON DELETE CASCADE,
    summary_id    UUID REFERENCES summaries(id) ON DELETE CASCADE,
    added_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (collection_id, summary_id)
);
CREATE INDEX IF NOT EXISTS idx_collection_papers_summary ON collection_papers(summary_id);

DROP TRIGGER IF EXISTS update_collections_updated_at ON collections;
CREATE TRIGGER update_collections_updated_at
    BEFORE UPDATE ON collections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE collections DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS collections_user_policy ON collections;

-- ─── 9. MIGRATION 005: Temporal Graph ────────────────────────

ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS published_date  DATE,
    ADD COLUMN IF NOT EXISTS arxiv_version   INTEGER DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_summaries_pubdate
    ON summaries(published_date ASC NULLS LAST);

CREATE TABLE IF NOT EXISTS paper_lineage (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ancestor_id      UUID REFERENCES summaries(id) ON DELETE CASCADE,
    descendant_id    UUID REFERENCES summaries(id) ON DELETE CASCADE,
    link_type        VARCHAR(30) DEFAULT 'cites',
    link_confidence  DECIMAL(5,4) DEFAULT 0.7,
    inferred_by      VARCHAR(20) DEFAULT 'citation',
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ancestor_id, descendant_id)
);
CREATE INDEX IF NOT EXISTS idx_lineage_ancestor   ON paper_lineage(ancestor_id);
CREATE INDEX IF NOT EXISTS idx_lineage_descendant ON paper_lineage(descendant_id);
CREATE INDEX IF NOT EXISTS idx_lineage_type       ON paper_lineage(link_type);
