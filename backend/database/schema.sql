-- Supabase PostgreSQL Schema for Research Paper Summarizer
-- This schema includes users, summaries, and user activity tracking

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table
CREATE TABLE users (
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

-- Summaries table
CREATE TABLE summaries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    paper_title TEXT NOT NULL,
    paper_authors TEXT[],
    paper_url TEXT,
    arxiv_id VARCHAR(50),
    
    -- Summary content (JSON for flexibility)
    summary_data JSONB NOT NULL,
    
    -- Metadata
    model_used VARCHAR(100) DEFAULT 'LED',
    processing_time_seconds DECIMAL(10, 2),
    word_count INTEGER,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Search optimization
    search_vector tsvector
);

-- User activity tracking
CREATE TABLE user_activity (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL, -- 'search', 'summarize', 'export', 'view'
    activity_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX idx_summaries_user_id ON summaries(user_id);
CREATE INDEX idx_summaries_created_at ON summaries(created_at DESC);
CREATE INDEX idx_summaries_arxiv_id ON summaries(arxiv_id);
CREATE INDEX idx_user_activity_user_id ON user_activity(user_id);
CREATE INDEX idx_user_activity_created_at ON user_activity(created_at DESC);
CREATE INDEX idx_summaries_search ON summaries USING GIN(search_vector);

-- Create full-text search trigger
CREATE OR REPLACE FUNCTION summaries_search_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := 
        setweight(to_tsvector('english', coalesce(NEW.paper_title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(array_to_string(NEW.paper_authors, ' '), '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER summaries_search_trigger
    BEFORE INSERT OR UPDATE ON summaries
    FOR EACH ROW EXECUTE FUNCTION summaries_search_update();

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_summaries_updated_at
    BEFORE UPDATE ON summaries
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Row Level Security (RLS) Policies
ALTER TABLE summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_activity ENABLE ROW LEVEL SECURITY;

-- Users can only see their own summaries
CREATE POLICY summaries_user_policy ON summaries
    FOR ALL USING (user_id = current_setting('app.user_id')::UUID);

-- Users can only see their own activity
CREATE POLICY activity_user_policy ON user_activity
    FOR ALL USING (user_id = current_setting('app.user_id')::UUID);

-- Sample views for analytics
CREATE VIEW user_summary_stats AS
SELECT 
    u.id as user_id,
    u.email,
    COUNT(s.id) as total_summaries,
    AVG(s.processing_time_seconds) as avg_processing_time,
    SUM(s.word_count) as total_words_processed,
    MAX(s.created_at) as last_summary_date,
    COUNT(DISTINCT DATE(s.created_at)) as active_days
FROM users u
LEFT JOIN summaries s ON u.id = s.user_id
GROUP BY u.id, u.email;
