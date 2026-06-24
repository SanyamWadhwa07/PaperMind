-- Migration 007: Personalization tables

-- Extend users table with researcher profile fields
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS research_focus TEXT[],
    ADD COLUMN IF NOT EXISTS expertise_level VARCHAR(20) DEFAULT 'researcher',
    ADD COLUMN IF NOT EXISTS preferred_summary_depth VARCHAR(20) DEFAULT 'detailed';

-- Paper annotations (highlight + annotate any section)
CREATE TABLE IF NOT EXISTS paper_annotations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    summary_id UUID REFERENCES summaries(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    section_key VARCHAR(100),
    highlighted_text TEXT,
    annotation_text TEXT,
    color VARCHAR(7) DEFAULT '#fbbf24',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_annotations_summary
    ON paper_annotations(summary_id);
CREATE INDEX IF NOT EXISTS idx_annotations_user
    ON paper_annotations(user_id);

-- Reading queue with priority scoring
CREATE TABLE IF NOT EXISTS reading_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    summary_id UUID REFERENCES summaries(id) ON DELETE CASCADE,
    priority_score DECIMAL(5,4) DEFAULT 0.5,
    -- status: pending | reading | done
    status VARCHAR(20) DEFAULT 'pending',
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, summary_id)
);

CREATE INDEX IF NOT EXISTS idx_reading_queue_user_status
    ON reading_queue(user_id, status);
CREATE INDEX IF NOT EXISTS idx_reading_queue_priority
    ON reading_queue(user_id, priority_score DESC);
