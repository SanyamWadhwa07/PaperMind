-- The three stored functions that `experience_schema.sql` defines and a live
-- database provisioned incrementally does not have. Same cause as
-- `002_missing_views.sql`: that file puts its tables at the top and its
-- functions and views at the bottom, so a partial run creates the tables and
-- silently skips everything below them.
--
-- The symptom is a PGRST202 traceback on every processed paper —
--
--   Could not find the function public.update_result_baseline(
--     p_dataset, p_metric, p_model, p_value) in the schema cache
--
-- — repeated once per extracted metric. Each call is caught and logged by
-- `core/memory/experience_db.py`, so nothing fails outright; the agents just
-- never accumulate any cross-paper experience, which is the whole point of
-- these tables. The noise in the log is the visible half of the problem.
--
-- Every statement is CREATE OR REPLACE and no table is touched, so running
-- this twice is safe.
--
-- Run this in the Supabase SQL editor.

-- ── Used by ExperienceStore.record_entity() ─────────────────────────────────

-- Accumulate one sighting of an entity, keeping a running mean of the
-- confidence the agents assigned it.
CREATE OR REPLACE FUNCTION update_entity_knowledge(
    p_entity_name VARCHAR(255),
    p_entity_type VARCHAR(50),
    p_confidence DECIMAL(5, 4),
    p_context TEXT,
    p_validating_agent VARCHAR(100)
) RETURNS VOID AS $$
BEGIN
    INSERT INTO entity_knowledge (entity_name, entity_type, frequency_count, confidence_score, typical_contexts, validated_by_agents)
    VALUES (
        p_entity_name,
        p_entity_type,
        1,
        p_confidence,
        jsonb_build_array(p_context),
        ARRAY[p_validating_agent]
    )
    ON CONFLICT (entity_name, entity_type) DO UPDATE SET
        frequency_count = entity_knowledge.frequency_count + 1,
        confidence_score = (entity_knowledge.confidence_score * entity_knowledge.frequency_count + p_confidence) / (entity_knowledge.frequency_count + 1),
        typical_contexts = entity_knowledge.typical_contexts || jsonb_build_array(p_context),
        last_seen = CURRENT_TIMESTAMP,
        validated_by_agents = array_append(entity_knowledge.validated_by_agents, p_validating_agent);
END;
$$ LANGUAGE plpgsql;


-- ── Used by ExperienceStore.record_pattern_result() ─────────────────────────

-- Track how often an extraction regex actually succeeds, per domain.
CREATE OR REPLACE FUNCTION update_pattern_performance(
    p_pattern_id VARCHAR(100),
    p_pattern_type VARCHAR(50),
    p_success BOOLEAN,
    p_domain VARCHAR(50)
) RETURNS VOID AS $$
BEGIN
    INSERT INTO pattern_performance (pattern_id, pattern_type, total_attempts, successful_extractions)
    VALUES (p_pattern_id, p_pattern_type, 1, CASE WHEN p_success THEN 1 ELSE 0 END)
    ON CONFLICT (pattern_id, pattern_type) DO UPDATE SET
        total_attempts = pattern_performance.total_attempts + 1,
        successful_extractions = pattern_performance.successful_extractions + CASE WHEN p_success THEN 1 ELSE 0 END,
        precision_score = (pattern_performance.successful_extractions + CASE WHEN p_success THEN 1 ELSE 0 END)::DECIMAL / (pattern_performance.total_attempts + 1),
        last_updated = CURRENT_TIMESTAMP;
END;
$$ LANGUAGE plpgsql;


-- ── Used by ExperienceStore.update_result_baseline() ────────────────────────

-- Maintain a running mean and standard deviation per (dataset, metric, model)
-- so a later paper's number can be recognised as an outlier. Welford's online
-- algorithm, so no history has to be kept to update the variance.
CREATE OR REPLACE FUNCTION update_result_baseline(
    p_dataset VARCHAR(255),
    p_metric VARCHAR(100),
    p_model VARCHAR(255),
    p_value DECIMAL(10, 4)
) RETURNS VOID AS $$
DECLARE
    v_count INTEGER;
    v_mean DECIMAL(10, 4);
    v_m2 DECIMAL(10, 4);
    v_delta DECIMAL(10, 4);
    v_delta2 DECIMAL(10, 4);
    v_variance DECIMAL(10, 4);
    v_std_dev DECIMAL(10, 4);
BEGIN
    SELECT sample_count, mean_value, (std_dev * std_dev * sample_count)
    INTO v_count, v_mean, v_m2
    FROM result_baselines
    WHERE dataset_name = p_dataset AND metric_name = p_metric AND
          (model_name = p_model OR (model_name IS NULL AND p_model IS NULL));

    IF NOT FOUND THEN
        -- First data point: no spread to speak of yet.
        INSERT INTO result_baselines (dataset_name, metric_name, model_name, min_value, max_value, mean_value, std_dev, sample_count)
        VALUES (p_dataset, p_metric, p_model, p_value, p_value, p_value, 0, 1);
    ELSE
        v_count := v_count + 1;
        v_delta := p_value - v_mean;
        v_mean := v_mean + v_delta / v_count;
        v_delta2 := p_value - v_mean;
        v_m2 := v_m2 + v_delta * v_delta2;
        v_variance := v_m2 / v_count;
        v_std_dev := SQRT(v_variance);

        UPDATE result_baselines SET
            min_value = LEAST(min_value, p_value),
            max_value = GREATEST(max_value, p_value),
            mean_value = v_mean,
            std_dev = v_std_dev,
            sample_count = v_count,
            outlier_threshold_low = v_mean - 2 * v_std_dev,
            outlier_threshold_high = v_mean + 2 * v_std_dev,
            last_updated = CURRENT_TIMESTAMP
        WHERE dataset_name = p_dataset AND metric_name = p_metric AND
              (model_name = p_model OR (model_name IS NULL AND p_model IS NULL));
    END IF;
END;
$$ LANGUAGE plpgsql;
