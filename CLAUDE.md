# PaperMind Developer Guide

## Project Overview

PaperMind is an AI-powered research paper summarization platform that transforms academic PDFs into structured, multi-level summaries using a 7-agent parallel processing pipeline. It extracts entities, quantitative results, figures, and citations, then generates four distinct summary types (Simple, Detailed, ELI5, Technical).

```
User uploads PDF / arXiv ID
        │
        ▼
┌─────────────────────────────────────────────────┐
│              Flask Backend (port 5000)           │
│                                                 │
│  auth/   routes/   database/   tasks/           │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│        ParallelAgentOrchestrator                │
│                                                 │
│  Phase 1 (sequential):                         │
│    StructureAgent → extract PDF sections        │
│                                                 │
│  Phase 2 (parallel):                           │
│    EntityAgent   ResultsAgent                   │
│    FigureAgent   ReasoningAgent                 │
│                                                 │
│  Phase 3 (sequential):                         │
│    SummaryAgent → LLM (Ollama qwen2.5:3b)       │
│    ComparisonAgent → SOTA benchmarking          │
└─────────────────────────────────────────────────┘
                     │
                     ▼
        Supabase PostgreSQL + pgvector
                     │
                     ▼
        React Frontend (port 5173)
```

---

## Repository Structure

```
PaperMind/
├── CLAUDE.md                     # This file
├── README.md
├── requirements.txt              # Root Python deps (pip install here)
│
├── backend/
│   ├── app.py                    # Main Flask app, all legacy routes
│   ├── main.py                   # PDF extraction pipeline (ImprovedPDFExtractor, etc.)
│   ├── patterns.json             # Regex patterns for entity/result extraction
│   ├── requirements.txt          # Backend-specific deps
│   ├── setup_database.py         # Supabase schema initialization script
│   ├── auth/
│   │   ├── routes.py             # /api/auth/* (register, login, me, reset-password)
│   │   └── utils.py              # JWT token creation/validation, bcrypt helpers
│   ├── database/
│   │   ├── config.py             # SUPABASE_URL, SUPABASE_SERVICE_KEY from .env
│   │   ├── schema.sql            # Core tables: users, summaries, user_activity
│   │   ├── experience_schema.sql # Agent learning tables
│   │   └── migrations/           # Incremental DB migrations (001–005+)
│   ├── routes/
│   │   ├── process_paper.py      # /api/process/upload, /api/process/arxiv (auth required)
│   │   ├── summaries.py          # /api/summaries CRUD (auth required)
│   │   ├── profile.py            # /api/profile/* (auth required)
│   │   ├── knowledge_graph.py    # /api/graph/* (semantic search, recommendations)
│   │   ├── feedback.py           # /api/feedback/* (star ratings)
│   │   ├── collections.py        # /api/collections/* (paper folders)
│   │   └── batch_compare.py      # /api/batch/compare (cross-paper comparison)
│   ├── tasks/
│   │   └── paper_tasks.py        # Celery async task definitions
│   └── uploads/, arxiv_papers/   # Temporary file storage
│
├── core/
│   ├── agent_integration.py      # AgentPaperProcessor wrapper, run_agent_mode()
│   ├── agents/
│   │   ├── base_agent.py         # BaseAgent ABC with async process(), stats
│   │   ├── message_bus.py        # Priority queue inter-agent communication
│   │   ├── orchestrator.py       # ParallelAgentOrchestrator (3-phase execution)
│   │   ├── structure_agent.py    # PDF section extraction (font-based detection)
│   │   ├── entity_agent.py       # Model/dataset/metric/framework extraction
│   │   ├── results_agent.py      # Quantitative results from tables + text
│   │   ├── figure_agent.py       # Figure extraction + relevance ranking
│   │   ├── reasoning_agent.py    # Key claims + contribution analysis
│   │   ├── summary_agent.py      # LLM-powered 4-type summary generation
│   │   └── comparison_agent.py   # SOTA benchmarking (optional)
│   ├── knowledge/
│   │   ├── embedding_service.py  # sentence-transformers singleton (all-MiniLM-L6-v2)
│   │   ├── citation_extractor.py # Reference section parser + arXiv ID matching
│   │   ├── graph_service.py      # Knowledge graph queries + similarity caching
│   │   ├── lineage_service.py    # Temporal paper linking (ancestry trees)
│   │   └── comparison_service.py # Cross-paper metrics/entity comparison
│   ├── llm/
│   │   └── llm_interface.py      # LocalLLM: Ollama → Transformers → Template fallback
│   ├── memory/
│   │   └── experience_db.py      # ExperienceStore: cross-paper learning in Supabase
│   └── pipeline/
│       ├── text_cleaner.py       # PDF text post-processing (fix hyphenation, fragments)
│       └── processing_cache.py   # Redis SHA256 cache for PDF processing results
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js            # API proxy → localhost:5000
│   └── src/
│       ├── App.jsx               # Routes: /, /login, /signup, /dashboard, /summary/:id,
│       │                         #   /batch, /profile, /timeline
│       ├── contexts/
│       │   ├── AuthContext.jsx   # JWT token management, user state
│       │   └── ToastContext.jsx
│       ├── pages/
│       │   ├── HomePage.jsx      # Landing: upload PDF or enter arXiv ID
│       │   ├── DashboardPage.jsx # Paper library with search + Collections sidebar
│       │   ├── SummaryPage.jsx   # Tabs: summaries, entities, figures, graph
│       │   ├── BatchPage.jsx     # Batch processing + Compare All button
│       │   ├── TimelinePage.jsx  # Research timeline + ancestry tree visualization
│       │   └── ProfilePage.jsx
│       └── components/
│           ├── KnowledgeGraph.jsx    # vis-network knowledge graph
│           ├── ComparisonTable.jsx   # Cross-paper metrics matrix
│           ├── StarRating.jsx        # 5-star feedback widget
│           ├── EntityDisplay.jsx     # Datasets/models/metrics chips
│           ├── FiguresDisplay.jsx    # Figure gallery
│           ├── FlowchartViewer.jsx   # Mermaid methodology flowchart
│           └── SectionSummaries.jsx  # Per-section accordion
│
└── tests/
    ├── conftest.py               # Fixtures: mock Supabase, LLM, test PDF
    ├── pytest.ini
    ├── unit/
    │   ├── test_text_cleaner.py
    │   ├── test_citation_extractor.py
    │   ├── test_summary_quality.py
    │   └── test_embedding_service.py
    ├── integration/
    │   ├── test_process_paper.py
    │   └── test_knowledge_graph.py
    └── api/
        └── test_routes.py
```

---

## Development Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- Ollama (https://ollama.com)
- Redis (for async task queue)
- Supabase project (free tier works)

### 1. Backend

```bash
cd backend
python -m venv research
# Windows:
.\research\Scripts\Activate.ps1
# Mac/Linux:
source research/bin/activate

pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Fill in: SUPABASE_URL, SUPABASE_SERVICE_KEY, JWT_SECRET_KEY
```

Run database migrations in order:
```bash
# Via Supabase dashboard SQL editor, run:
backend/database/schema.sql
backend/database/experience_schema.sql
backend/database/migrations/001_knowledge_graph.sql
backend/database/migrations/002_summary_quality.sql
backend/database/migrations/003_user_feedback.sql
backend/database/migrations/004_collections.sql
backend/database/migrations/005_temporal_graph.sql
```

Start Flask dev server:
```bash
cd backend
python app.py
# Runs on http://localhost:5000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:5173 (proxies /api/* to localhost:5000)
```

### 3. Ollama (LLM)

```bash
# Install from https://ollama.com, then:
ollama pull qwen2.5:3b           # Default (fast, ~2GB)
ollama pull qwen2.5:7b-instruct-q4_K_M  # Better quality (~4GB)
ollama serve                     # Start server on :11434
```

Override model via env var: `PAPERMIND_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M`

### 4. Redis (async tasks)

```bash
# Windows: use WSL or Docker
docker run -d -p 6379:6379 redis:alpine
# Mac: brew install redis && redis-server
```

### 5. Celery Worker

```bash
cd backend
celery -A tasks.paper_tasks worker --loglevel=info
```

---

## The 7-Agent Pipeline

| Agent | Phase | Input | Output |
|-------|-------|-------|--------|
| `StructureAgent` | 1 (sequential) | PDF path | sections dict, domain |
| `EntityAgent` | 2 (parallel) | sections, domain | models, datasets, metrics, tasks |
| `ResultsAgent` | 2 (parallel) | sections | quantitative results list |
| `FigureAgent` | 2 (parallel) | PDF path, sections | figures with captions + rank |
| `ReasoningAgent` | 2 (parallel) | sections, entities | claims, contributions, limitations |
| `SummaryAgent` | 3 (sequential) | all above outputs | 4 summaries + section summaries |
| `ComparisonAgent` | 3 (sequential) | results, entities | SOTA comparison (optional) |

**Inter-agent communication** uses `AgentMessageBus` (priority queue). Agents can broadcast `CONFLICT` messages when disagreeing on extracted values; the orchestrator resolves via voting.

**Domain detection** (`StructureAgent`) returns `cv`, `nlp`, `ml`, or `general`, which drives domain-specific prompts in `SummaryAgent` and entity patterns in `EntityAgent`.

---

## Database Schema

### Core Tables (`schema.sql`)

| Table | Purpose |
|-------|---------|
| `users` | Auth, profile, avatar |
| `summaries` | Paper summaries (JSONB `summary_data` stores full agent output) |
| `user_activity` | Event log: search, summarize, export, view |

### Knowledge Graph Tables (`migrations/001`)

| Table | Purpose |
|-------|---------|
| `paper_citations` | Extracted bibliography entries per paper |
| `paper_similarity` | Pre-computed top-K cosine similarity pairs (pgvector) |
| `summaries.embedding` | 384-dim vector (all-MiniLM-L6-v2) for each paper |

### Experience Tables (`experience_schema.sql`)

| Table | Purpose |
|-------|---------|
| `entity_knowledge` | Cross-paper entity confidence accumulation |
| `pattern_performance` | Regex success rates per domain |
| `result_baselines` | Running mean/std for (dataset, metric, model) triples |
| `entity_relationships` | Entity co-occurrence / semantic relationships |

### Additional Tables

| Table | Migration | Purpose |
|-------|-----------|---------|
| `summary_feedback` | 003 | 1–5 star ratings + comments |
| `collections` | 004 | User paper folders |
| `collection_papers` | 004 | M2M: collection ↔ summary |
| `paper_lineage` | 005 | Temporal ancestor/descendant links |

---

## API Reference

All authenticated routes require: `Authorization: Bearer <jwt_token>`

### Auth
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/register` | — | Create account |
| POST | `/api/auth/login` | — | Get JWT token |
| GET | `/api/auth/me` | ✓ | Current user profile |

### Paper Processing
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/process/upload` | ✓ | Upload PDF → process → save to DB |
| POST | `/api/process/arxiv` | ✓ | arXiv ID → download → process → save |
| GET | `/api/status/<task_id>` | — | Async task status |

### Summaries
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/summaries` | ✓ | List with pagination + search |
| GET | `/api/summaries/<id>` | ✓ | Single summary |
| DELETE | `/api/summaries/<id>` | ✓ | Delete |
| GET | `/api/export/<id>` | ✓ | Export: `?format=json\|markdown\|bibtex` |

### Knowledge Graph
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/graph/paper/<id>` | ✓ | Paper's entity/paper graph |
| POST | `/api/graph/search` | ✓ | Semantic vector search |
| GET | `/api/graph/recommendations/<id>` | ✓ | Top-5 similar papers |
| GET | `/api/graph/timeline` | ✓ | All papers with dates + lineage edges |
| GET | `/api/graph/ancestry/<id>` | ✓ | Ancestor/descendant tree |

### Feedback & Collections
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/feedback/summary/<id>` | ✓ | Submit rating + comment |
| POST | `/api/collections` | ✓ | Create collection |
| POST | `/api/collections/<id>/papers` | ✓ | Add paper to collection |
| POST | `/api/batch/compare` | ✓ | Cross-paper comparison (up to 10) |

---

## Common Development Tasks

### Adding a New Agent

1. Create `core/agents/my_agent.py` extending `BaseAgent`
2. Implement `async def process(self, input_data: Dict) -> Dict`
3. Add to `ParallelAgentOrchestrator.__init__()` in `orchestrator.py`
4. Register in Phase 2 parallel gather or Phase 3 sequential block
5. Add agent output to `_aggregate_results()` in `orchestrator.py`

### Adding a New API Endpoint

1. Create or find the Blueprint in `backend/routes/`
2. Register it in `backend/app.py` with `app.register_blueprint(bp, url_prefix='/api')`
3. Use `@token_required` from `auth.utils` for protected routes
4. Return `jsonify({...}), status_code`

### Running Database Migrations

Run SQL files in order via Supabase dashboard or `psql`:
```bash
psql $DATABASE_URL -f backend/database/migrations/00X_name.sql
```

### Running Tests

```bash
cd PaperMind
pip install pytest pytest-asyncio pytest-mock
pytest tests/ -v
pytest tests/unit/ -v          # Unit tests only
pytest tests/api/ -v           # API route tests only
```

### Changing the LLM Model

```bash
# Option 1: Environment variable (no code change)
export PAPERMIND_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M

# Option 2: config.yaml
llm_backend: ollama
llm_model: qwen2.5:7b-instruct-q4_K_M
llm_max_tokens: 1024

# Option 3: .env
PAPERMIND_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M
```

---

## Configuration

Environment variables (`.env`):

```bash
# Required
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
JWT_SECRET_KEY=your-super-secret-256bit-key

# Optional
PAPERMIND_LLM_MODEL=qwen2.5:3b     # override Ollama model
REDIS_URL=redis://localhost:6379/0  # for Celery + caching
SENTRY_DSN=https://...@sentry.io/X # error monitoring
FLASK_ENV=development
FLASK_DEBUG=True
```

`config.yaml` (optional, backend/ root):

```yaml
llm_backend: ollama
llm_model: qwen2.5:3b
llm_max_tokens: 1024
llm_temperature: 0.7
experience_enabled: true
max_figures: 10
max_entities: 15
max_results: 50
enable_ocr: true
```

---

## Key Architecture Decisions

- **pgvector over Pinecone**: all data stays in Supabase, no extra service
- **all-MiniLM-L6-v2 over SciBERT**: faster inference, 80MB model, comparable semantic similarity
- **Ollama-first LLM**: zero API costs, privacy-preserving, runs on consumer GPU (RTX 2050 4GB)
- **JSONB for summary_data**: flexible schema evolution without migrations for new agent output fields
- **Celery + Redis**: replaces fragile in-memory `processing_status` dict that loses state on restart
