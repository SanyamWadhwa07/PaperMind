-- Disable Row Level Security for authentication to work
-- Run this in Supabase SQL Editor

ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE summaries DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_activity DISABLE ROW LEVEL SECURITY;

-- Drop the restrictive policies
DROP POLICY IF EXISTS summaries_user_policy ON summaries;
DROP POLICY IF EXISTS activity_user_policy ON user_activity;
