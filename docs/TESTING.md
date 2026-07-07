# Testing

## Status

**90/90 tests passing** · **42% statement coverage** across `core/` + `backend/`

```
tests/unit/          62 tests   — pure-logic units: text cleaning, citation parsing,
                                  embeddings, entity extraction, structure detection,
                                  summary-quality scoring, LangGraph summary engine
tests/integration/   10 tests   — multi-agent pipeline wiring, knowledge-graph queries
tests/api/           18 tests   — FastAPI route contracts (auth, process, summaries, graph)
```

Run everything:

```bash
pip install -r requirements.txt -r backend/requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

With coverage:

```bash
pytest tests/ --cov=core --cov=backend --cov-report=term
```

CI runs the full suite with coverage on every push/PR to `main` — see
[`.github/workflows/tests.yml`](../.github/workflows/tests.yml).

## Coverage by area

Coverage is deliberately uneven: pure extraction/parsing logic (the part most
worth unit-testing) is well covered, while thin I/O wrappers around Supabase/
Flask routes are not, since those are exercised by the integration/API tests
and manual smoke-testing instead.

| Module | Stmts | Cover |
|---|---|---|
| `core/graph/adapter.py` | 31 | 100% |
| `core/graph/schemas.py` | 39 | 100% |
| `core/knowledge/citation_extractor.py` | 68 | 91% |
| `core/pipeline/text_cleaner.py` | 64 | 98% |
| `core/graph/summary_graph.py` | 210 | 81% |
| `core/agent_integration.py` | 115 | 83% |
| `core/agents/research_gap_agent.py` | 60 | 87% |
| `core/agents/reproducibility_agent.py` | 34 | 85% |
| `core/agents/entity_agent.py` | 143 | 78% |
| `core/agents/orchestrator.py` | 157 | 73% |
| `core/agents/structure_agent.py` | 121 | 72% |
| `core/knowledge/embedding_service.py` | 36 | 75% |
| `core/agents/reasoning_agent.py` | 107 | 69% |
| `core/agents/summary_agent.py` | 213 | 69% |
| `core/agents/base_agent.py` | 132 | 66% |
| `core/llm/providers.py` | 94 | 51% |
| `core/pipeline/pdf_extractor.py` | 221 | 51% |
| `core/agents/message_bus.py` | 173 | 45% |

Full breakdown: run the coverage command above, or check the `coverage-report`
artifact uploaded by CI.

## What's *not* covered (and why)

- `backend/app.py`, `backend/auth/supabase_auth.py` — legacy Flask entry points
  superseded by `backend/main_app.py` (FastAPI); kept for reference, not
  exercised by tests.
- `core/knowledge/{arxiv_diff_service,github_service,semantic_scholar_service,topic_clustering}.py` —
  optional integrations that require live external APIs; excluded from unit
  tests by design, validated manually.
- `core/pipeline/diagram_processor.py`, `core/llm/llm_interface.py` — heavy
  ML/LLM call sites; covered indirectly through the end-to-end benchmark in
  [`evals/`](../evals/run_benchmark.py) rather than mocked unit tests.

## End-to-end quality benchmark

Unit/integration tests check that the code *runs correctly*. They don't tell
you whether the pipeline's *output* is any good on a real paper. For that,
see [`evals/run_benchmark.py`](../evals/run_benchmark.py) and
[`docs/BENCHMARKS.md`](BENCHMARKS.md), which run the full 10-agent pipeline
against real arXiv PDFs and score it on latency, extraction coverage, and
ROUGE summary quality against each paper's own abstract.
