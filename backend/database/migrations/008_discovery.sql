-- Migration 008: Discovery and topic clustering tables

-- Venue/conference tracking on papers
ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS venue VARCHAR(255),
    ADD COLUMN IF NOT EXISTS venue_year INTEGER;

CREATE INDEX IF NOT EXISTS idx_summaries_venue
    ON summaries(venue) WHERE venue IS NOT NULL;

-- GitHub repo links extracted from papers
CREATE TABLE IF NOT EXISTS paper_github_links (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    summary_id UUID REFERENCES summaries(id) ON DELETE CASCADE,
    repo_url TEXT NOT NULL,
    repo_owner VARCHAR(255),
    repo_name VARCHAR(255),
    is_active BOOLEAN,
    readme_summary TEXT,
    stars INTEGER,
    last_checked TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(summary_id, repo_url)
);

CREATE INDEX IF NOT EXISTS idx_github_links_summary
    ON paper_github_links(summary_id);

-- Topic cluster assignments (populated by BERTopic offline job)
CREATE TABLE IF NOT EXISTS paper_topic_clusters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    summary_id UUID REFERENCES summaries(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    cluster_id INTEGER NOT NULL,
    cluster_label TEXT,
    cluster_keywords TEXT[],
    probability DECIMAL(5,4),
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(summary_id, cluster_id)
);

CREATE INDEX IF NOT EXISTS idx_topic_clusters_cluster
    ON paper_topic_clusters(user_id, cluster_id);
CREATE INDEX IF NOT EXISTS idx_topic_clusters_summary
    ON paper_topic_clusters(summary_id);
