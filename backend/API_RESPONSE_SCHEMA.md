# API Response Schema - Agent Mode

## Overview
The backend now uses the **agent-mode** system exclusively, which generates **4 distinct summaries** for each paper using parallel LLM agents.

## Response Format

### Summary Data Structure

```json
{
  "arxiv_id": "2511.15709v1",
  "title": "Paper Title",
  "authors": ["Author 1", "Author 2"],
  "published": "2025-11-19 18:59:56+00:00",
  "updated": "2025-11-19 18:59:56+00:00",
  
  "summaries": {
    "simple": "2-3 sentence straightforward summary for general audience",
    "detailed": "Comprehensive 300-400 word academic summary with methodology, findings, and significance",
    "eli5": "Explain Like I'm 5 version using simple analogies and accessible language",
    "technical": "Technical summary for domain experts with implementation details and quantitative metrics"
  },
  
  "key_findings": [
    "Main finding 1",
    "Main finding 2",
    "Main finding 3"
  ],
  
  "methodology": {
    "approach": "Description of methodology",
    "models": ["Model1", "Model2"],
    "datasets": ["Dataset1", "Dataset2"]
  },
  
  "results": {
    "summary": "Results summary",
    "metrics": [
      {
        "name": "Accuracy",
        "value": "95.2%",
        "dataset": "TestDataset"
      }
    ],
    "comparison": ["Comparison point 1", "Comparison point 2"]
  },
  
  "datasets": ["Dataset1", "Dataset2"],
  "models": ["Model1", "Model2"],
  "metrics": ["Accuracy", "F1-Score"],
  "tasks": ["Task1", "Task2"],
  
  "figures": [
    {
      "figure_number": 1,
      "caption": "Figure caption",
      "page": 3,
      "section": "results"
    }
  ],
  
  "limitations": ["Limitation 1", "Limitation 2"],
  "future_work": ["Future direction 1", "Future direction 2"],
  
  "agent_metadata": {
    "processing_mode": "parallel_agents",
    "total_time_ms": 47351.46,
    "speedup": 1.0,
    "agent_count": 6,
    "llm_backend": "ollama",
    "experience_applied": true,
    "agent_timeline": [
      {
        "agent": "StructureAgent",
        "time_ms": 0,
        "status": "completed"
      },
      {
        "agent": "EntityAgent",
        "time_ms": 0,
        "status": "completed"
      },
      {
        "agent": "ResultsAgent",
        "time_ms": 0,
        "status": "completed"
      },
      {
        "agent": "FigureAgent",
        "time_ms": 0,
        "status": "completed"
      },
      {
        "agent": "ReasoningAgent",
        "time_ms": 0,
        "status": "completed"
      },
      {
        "agent": "SummaryAgent",
        "time_ms": 0,
        "status": "completed"
      }
    ],
    "consensus_votes": 0,
    "conflicts_resolved": 0
  },
  
  "flagged_uncertainties": {
    "uncertain_entities": [],
    "outlier_results": [],
    "unsupported_claims": []
  }
}
```

## Key Changes from Standard Mode

### 1. Multiple Summary Types
Previously: Single `overall_summary` field
Now: **4 distinct summaries** in `summaries` object:
- `simple`: Quick 2-3 sentence overview
- `detailed`: Comprehensive academic summary
- `eli5`: Accessible explanation for non-experts
- `technical`: In-depth technical analysis

### 2. Enhanced Metadata
- `agent_metadata`: Contains processing time, agent count, LLM backend info
- `flagged_uncertainties`: System-identified areas needing human review

### 3. Structured Results
- Organized `methodology`, `results`, and `findings` sections
- Direct lists for `datasets`, `models`, `metrics`, `tasks`
- Future work and limitations explicitly extracted

## API Endpoints Updated

### POST /api/process/upload
Upload PDF and process with agent mode
- Returns: Summary with 4 distinct summaries

### POST /api/process/arxiv
Process paper from arXiv ID
- Returns: Summary with 4 distinct summaries

### POST /api/summarize
Synchronous summarization
- Returns: Summary with 4 distinct summaries

### POST /api/summarize/async
Asynchronous summarization
- Returns: task_id for status polling
- Result contains summary with 4 distinct summaries

### POST /api/batch/summarize
Batch processing multiple papers
- Returns: Array of summaries, each with 4 distinct summaries

## Database Schema

The `summaries` table stores the entire response in the `summary_data` JSONB column:

```sql
CREATE TABLE summaries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    paper_title TEXT NOT NULL,
    paper_authors TEXT[],
    paper_url TEXT,
    arxiv_id VARCHAR(50),
    summary_data JSONB NOT NULL,  -- Entire agent-mode response
    model_used VARCHAR(100),      -- e.g., "ollama-qwen2.5:3b"
    processing_time_seconds DECIMAL(10, 2),
    word_count INTEGER,           -- Sum of all 4 summaries
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

## Migration Notes

### Frontend Changes Required
1. Update UI to display 4 summary types instead of 1
2. Add tabs/accordion for switching between summary types
3. Display agent metadata (processing time, agents used)
4. Show structured methodology/results sections

### Example Frontend Usage

```javascript
// Fetch summary
const response = await fetch('/api/process/arxiv', {
  method: 'POST',
  body: JSON.stringify({ arxiv_id: '2511.15709' })
});

const data = await response.json();

// Access different summaries
console.log(data.summary_data.summaries.simple);    // Quick overview
console.log(data.summary_data.summaries.detailed);  // Academic summary
console.log(data.summary_data.summaries.eli5);      // Simple explanation
console.log(data.summary_data.summaries.technical); // Expert analysis

// Display metadata
console.log(`Processed in ${data.processing_time_seconds}s`);
console.log(`Using ${data.model_used}`);
```

## Benefits of Agent Mode

1. **Better Quality**: 4 specialized summaries instead of 1 generic summary
2. **No Truncation**: Full sections passed to LLM for intelligent length control
3. **Parallel Processing**: 6 agents run simultaneously for faster processing
4. **Experience Learning**: System learns from successful extractions
5. **Uncertainty Flagging**: Identifies areas needing human review
