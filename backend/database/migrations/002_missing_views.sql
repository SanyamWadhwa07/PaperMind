-- Views that `experience_schema.sql` defines but a live database provisioned
-- incrementally does not have. Every one of them is a VIEW; no table is
-- missing, so nothing here touches stored data and running it twice is safe.
--
-- Why they went missing: `experience_schema.sql` is one file with the tables at
-- the top and the views at the bottom, so a partial run (or a run that stopped
-- on an error in the middle) creates the tables and silently skips the views.
-- The code paths that read them then fail one by one, each caught and logged.
--
-- Run this in the Supabase SQL editor.

-- ── Used by core/memory/experience_db.py ────────────────────────────────────

-- Entity names the agents have seen often enough to trust without re-checking.
-- Read by ExperienceStore.get_high_confidence_entities().
CREATE OR REPLACE VIEW high_confidence_entities AS
SELECT entity_name, entity_type, frequency_count, confidence_score
FROM entity_knowledge
WHERE confidence_score >= 0.8 AND frequency_count >= 5
ORDER BY confidence_score DESC, frequency_count DESC;

-- Per-agent timing and success rate. Read by ExperienceStore.get_agent_performance().
CREATE OR REPLACE VIEW agent_performance_metrics AS
SELECT
    agent_name,
    COUNT(*)                                                        AS total_executions,
    AVG(execution_time_ms)                                          AS avg_execution_time_ms,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)::DECIMAL
        / NULLIF(COUNT(*), 0)                                       AS success_rate,
    AVG(confidence_avg)                                             AS avg_confidence,
    AVG(items_extracted)                                            AS avg_items_extracted
FROM agent_execution_log
GROUP BY agent_name;

-- ── Not read by any code today; analytics conveniences ─────────────────────
-- Kept so the database matches the schema file rather than diverging from it.

CREATE OR REPLACE VIEW pattern_effectiveness AS
SELECT
    pattern_id,
    pattern_type,
    precision_score,
    total_attempts,
    successful_extractions
FROM pattern_performance
WHERE total_attempts >= 5
ORDER BY precision_score DESC;

CREATE OR REPLACE VIEW expected_result_ranges AS
SELECT
    dataset_name,
    metric_name,
    model_name,
    mean_value,
    std_dev,
    outlier_threshold_low,
    outlier_threshold_high,
    sample_count
FROM result_baselines
WHERE sample_count >= 3;

CREATE OR REPLACE VIEW common_entity_pairs AS
SELECT
    entity_1,
    entity_1_type,
    entity_2,
    entity_2_type,
    relationship_type,
    frequency_count,
    confidence_score
FROM entity_relationships
WHERE frequency_count >= 2
ORDER BY frequency_count DESC;

-- NOTE: `user_summary_stats` is deliberately NOT recreated. StatsRepository now
-- aggregates over `summaries` directly, so the dashboard no longer depends on a
-- view existing. Recreating it would be harmless but pointless.
