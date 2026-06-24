-- Migration 009: store the RelationAgent's natural-language justification for a
-- paper-to-paper link, so the knowledge graph can show *why* two papers relate.

ALTER TABLE paper_lineage
    ADD COLUMN IF NOT EXISTS rationale TEXT;

-- Optional: distinguish LLM-derived links from citation-derived ones.
ALTER TABLE paper_lineage
    ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'citation';
