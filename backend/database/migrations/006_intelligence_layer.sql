-- Migration 006: Intelligence layer tables
-- Run via Supabase SQL editor or psql

-- Per-paper intelligence analysis cache
CREATE TABLE IF NOT EXISTS paper_intelligence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    summary_id UUID REFERENCES summaries(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    -- analysis_type: gaps | reproducibility | peer_review | ablation | contradictions
    analysis_type VARCHAR(50) NOT NULL,
    analysis_data JSONB NOT NULL,
    confidence_score DECIMAL(5,4),
    llm_backend VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(summary_id, analysis_type)
);

CREATE INDEX IF NOT EXISTS idx_paper_intelligence_summary
    ON paper_intelligence(summary_id);
CREATE INDEX IF NOT EXISTS idx_paper_intelligence_user
    ON paper_intelligence(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_intelligence_type
    ON paper_intelligence(analysis_type);

-- Corpus-level intelligence sessions (hypothesis generation, lit reviews)
CREATE TABLE IF NOT EXISTS intelligence_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    -- session_type: hypothesis | lit_review | contradiction_map
    session_type VARCHAR(50) NOT NULL,
    input_context JSONB,
    result_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_intelligence_sessions_user
    ON intelligence_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_intelligence_sessions_type
    ON intelligence_sessions(user_id, session_type);
