-- Experience Database Schema for Multi-Agent Learning System
-- Extends existing Supabase schema with agent experience tables

-- Entity Knowledge Table
-- Stores validated entities with confidence scores and frequency
CREATE TABLE IF NOT EXISTS entity_knowledge (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(50) NOT NULL, -- 'model', 'dataset', 'metric', 'framework'
    frequency_count INTEGER DEFAULT 1,
    confidence_score DECIMAL(5, 4) DEFAULT 0.5, -- 0.0 to 1.0
    typical_contexts JSONB, -- Array of common contexts where entity appears
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    validated_by_agents TEXT[], -- Array of agent names that validated this
    metadata JSONB, -- Additional info like typical sections, co-occurring entities
    UNIQUE(entity_name, entity_type)
);

-- Pattern Performance Table
-- Tracks success rates of regex patterns
CREATE TABLE IF NOT EXISTS pattern_performance (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pattern_id VARCHAR(100) NOT NULL, -- Reference to pattern in patterns.json
    pattern_type VARCHAR(50) NOT NULL, -- 'entity', 'result', 'contribution', etc.
    total_attempts INTEGER DEFAULT 0,
    successful_extractions INTEGER DEFAULT 0,
    false_positives INTEGER DEFAULT 0,
    precision_score DECIMAL(5, 4), -- successful / total_attempts
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    performance_by_domain JSONB, -- Performance broken down by paper domain (CV, NLP, etc.)
    UNIQUE(pattern_id, pattern_type)
);

-- Section Templates Table
-- Common structures observed in papers
CREATE TABLE IF NOT EXISTS section_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain VARCHAR(50), -- 'cv', 'nlp', 'ml', 'general'
    section_sequence TEXT[], -- e.g., ['intro', 'related', 'method', 'experiments', 'results']
    frequency_count INTEGER DEFAULT 1,
    confidence_score DECIMAL(5, 4) DEFAULT 0.5,
    average_section_lengths JSONB, -- {"intro": 1200, "method": 3500, ...}
    typical_subsections JSONB, -- Subsection patterns per section
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Result Baselines Table
-- Expected ranges for metrics on datasets
CREATE TABLE IF NOT EXISTS result_baselines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_name VARCHAR(255) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(255), -- NULL means aggregate across models
    min_value DECIMAL(10, 4),
    max_value DECIMAL(10, 4),
    mean_value DECIMAL(10, 4),
    std_dev DECIMAL(10, 4),
    sample_count INTEGER DEFAULT 1,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    outlier_threshold_low DECIMAL(10, 4), -- Mean - 2*std_dev
    outlier_threshold_high DECIMAL(10, 4), -- Mean + 2*std_dev
    UNIQUE(dataset_name, metric_name, model_name)
);

-- Agent Execution Log
-- Track agent performance and timing
CREATE TABLE IF NOT EXISTS agent_execution_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID, -- Reference to summaries table (optional)
    agent_name VARCHAR(100) NOT NULL,
    execution_time_ms INTEGER,
    status VARCHAR(50), -- 'success', 'failed', 'partial'
    items_extracted INTEGER,
    confidence_avg DECIMAL(5, 4),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Agent Consensus History
-- Record when agents agreed/disagreed
CREATE TABLE IF NOT EXISTS agent_consensus_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID,
    extraction_type VARCHAR(100), -- 'entity', 'result', 'claim'
    extracted_value TEXT,
    agents_voting JSONB, -- {"EntityAgent": "agree", "ReasoningAgent": "agree", ...}
    consensus_reached BOOLEAN,
    final_confidence DECIMAL(5, 4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Cross-Paper Knowledge Graph
-- Relationships between entities (e.g., "BERT often used with GLUE")
CREATE TABLE IF NOT EXISTS entity_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_1 VARCHAR(255) NOT NULL,
    entity_1_type VARCHAR(50) NOT NULL,
    entity_2 VARCHAR(255) NOT NULL,
    entity_2_type VARCHAR(50) NOT NULL,
    relationship_type VARCHAR(50), -- 'co-occurs', 'compared-to', 'uses', 'evaluated-on'
    frequency_count INTEGER DEFAULT 1,
    confidence_score DECIMAL(5, 4) DEFAULT 0.5,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_1, entity_1_type, entity_2, entity_2_type, relationship_type)
);

-- Create indexes for performance
CREATE INDEX idx_entity_knowledge_type ON entity_knowledge(entity_type);
CREATE INDEX idx_entity_knowledge_name ON entity_knowledge(entity_name);
CREATE INDEX idx_entity_knowledge_confidence ON entity_knowledge(confidence_score DESC);
CREATE INDEX idx_pattern_performance_type ON pattern_performance(pattern_type);
CREATE INDEX idx_section_templates_domain ON section_templates(domain);
CREATE INDEX idx_result_baselines_dataset ON result_baselines(dataset_name);
CREATE INDEX idx_result_baselines_metric ON result_baselines(metric_name);
CREATE INDEX idx_agent_execution_log_agent ON agent_execution_log(agent_name);
CREATE INDEX idx_agent_execution_log_created ON agent_execution_log(created_at DESC);
CREATE INDEX idx_entity_relationships_e1 ON entity_relationships(entity_1, entity_1_type);
CREATE INDEX idx_entity_relationships_e2 ON entity_relationships(entity_2, entity_2_type);

-- Functions for updating experience data

-- Update entity knowledge with new occurrence
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

-- Update pattern performance
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

-- Update result baseline with new data point
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
    -- Welford's online algorithm for running mean and variance
    SELECT sample_count, mean_value, (std_dev * std_dev * sample_count) 
    INTO v_count, v_mean, v_m2
    FROM result_baselines
    WHERE dataset_name = p_dataset AND metric_name = p_metric AND 
          (model_name = p_model OR (model_name IS NULL AND p_model IS NULL));
    
    IF NOT FOUND THEN
        -- First data point
        INSERT INTO result_baselines (dataset_name, metric_name, model_name, min_value, max_value, mean_value, std_dev, sample_count)
        VALUES (p_dataset, p_metric, p_model, p_value, p_value, p_value, 0, 1);
    ELSE
        -- Update statistics
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

-- Views for agent decision-making

-- High confidence entities (for validation)
CREATE VIEW high_confidence_entities AS
SELECT entity_name, entity_type, frequency_count, confidence_score
FROM entity_knowledge
WHERE confidence_score >= 0.8 AND frequency_count >= 5
ORDER BY confidence_score DESC, frequency_count DESC;

-- Pattern effectiveness ranking
CREATE VIEW pattern_effectiveness AS
SELECT 
    pattern_id,
    pattern_type,
    precision_score,
    total_attempts,
    successful_extractions,
    CASE 
        WHEN precision_score >= 0.9 THEN 'excellent'
        WHEN precision_score >= 0.7 THEN 'good'
        WHEN precision_score >= 0.5 THEN 'fair'
        ELSE 'poor'
    END as effectiveness_tier
FROM pattern_performance
WHERE total_attempts >= 10
ORDER BY precision_score DESC;

-- Expected result ranges (for outlier detection)
CREATE VIEW expected_result_ranges AS
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

-- Common entity pairs (for relationship inference)
CREATE VIEW common_entity_pairs AS
SELECT 
    entity_1,
    entity_1_type,
    entity_2,
    entity_2_type,
    relationship_type,
    frequency_count,
    confidence_score
FROM entity_relationships
WHERE frequency_count >= 3 AND confidence_score >= 0.6
ORDER BY frequency_count DESC;

-- Agent performance metrics
CREATE VIEW agent_performance_metrics AS
SELECT 
    agent_name,
    COUNT(*) as total_executions,
    AVG(execution_time_ms) as avg_execution_time_ms,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)::DECIMAL / COUNT(*) as success_rate,
    AVG(confidence_avg) as avg_confidence,
    AVG(items_extracted) as avg_items_extracted
FROM agent_execution_log
GROUP BY agent_name;

COMMENT ON TABLE entity_knowledge IS 'Validated entities with frequency and confidence scores';
COMMENT ON TABLE pattern_performance IS 'Tracks regex pattern success rates for continuous improvement';
COMMENT ON TABLE section_templates IS 'Common paper structure patterns by domain';
COMMENT ON TABLE result_baselines IS 'Expected metric ranges for outlier detection';
COMMENT ON TABLE agent_execution_log IS 'Agent performance tracking';
COMMENT ON TABLE agent_consensus_history IS 'Multi-agent agreement tracking';
COMMENT ON TABLE entity_relationships IS 'Cross-paper entity relationship graph';
