-- Migration 005: Temporal knowledge graph — publication dates + paper lineage
ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS published_date  DATE,
    ADD COLUMN IF NOT EXISTS arxiv_version   INTEGER DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_summaries_pubdate
    ON summaries(published_date ASC NULLS LAST);

-- Research lineage: directed edge from ancestor (older) to descendant (newer)
CREATE TABLE IF NOT EXISTS paper_lineage (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ancestor_id      UUID REFERENCES summaries(id) ON DELETE CASCADE,
    descendant_id    UUID REFERENCES summaries(id) ON DELETE CASCADE,
    link_type        VARCHAR(30) DEFAULT 'cites',
        -- 'cites' | 'extends' | 'replicates' | 'contradicts' | 'inspired_by'
    link_confidence  DECIMAL(5,4) DEFAULT 0.7,
    inferred_by      VARCHAR(20) DEFAULT 'citation',
        -- 'citation' | 'similarity' | 'manual'
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ancestor_id, descendant_id)
);
CREATE INDEX IF NOT EXISTS idx_lineage_ancestor    ON paper_lineage(ancestor_id);
CREATE INDEX IF NOT EXISTS idx_lineage_descendant  ON paper_lineage(descendant_id);
CREATE INDEX IF NOT EXISTS idx_lineage_type        ON paper_lineage(link_type);
