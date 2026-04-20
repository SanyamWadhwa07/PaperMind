-- Migration 003: User feedback (star ratings + comments)
CREATE TABLE IF NOT EXISTS summary_feedback (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    summary_id    UUID REFERENCES summaries(id) ON DELETE CASCADE,
    user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
    rating        INTEGER CHECK (rating BETWEEN 1 AND 5),
    feedback_type VARCHAR(50) DEFAULT 'rating',  -- 'rating' | 'error_report' | 'flag_hallucination'
    comment       TEXT,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(summary_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_summary ON summary_feedback(summary_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user    ON summary_feedback(user_id);
