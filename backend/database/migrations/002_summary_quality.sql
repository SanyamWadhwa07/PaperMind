-- Migration 002: Summary quality score column
ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS quality_score DECIMAL(5,4);

CREATE INDEX IF NOT EXISTS idx_summaries_quality
    ON summaries(quality_score DESC)
    WHERE quality_score IS NOT NULL;
