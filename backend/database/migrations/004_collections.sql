-- Migration 004: Paper collections (user-defined folders)
CREATE TABLE IF NOT EXISTS collections (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    color       VARCHAR(7) DEFAULT '#6366f1',  -- hex color for UI
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

-- Auto-update updated_at for collections
CREATE TRIGGER update_collections_updated_at
    BEFORE UPDATE ON collections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- RLS: users only see their own collections
ALTER TABLE collections ENABLE ROW LEVEL SECURITY;
CREATE POLICY collections_user_policy ON collections
    FOR ALL USING (user_id = current_setting('app.user_id')::UUID);
