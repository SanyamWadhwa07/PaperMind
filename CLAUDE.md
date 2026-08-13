# PaperMind Developer Guide

## Project Overview

PaperMind is an AI-powered research paper platform that turns academic PDFs
into structured, multi-level summaries. Upload a PDF or paste an arXiv ID and
a multi-agent pipeline extracts sections, entities, quantitative results, and
figures, then a LangGraph-based engine writes a full-paper summary plus
findings, contributions, limitations, and future work. A separate
`intelligence` layer adds on-demand features: simulated peer review,
reproducibility scoring, research-gap detection, and slide generation.

```
User uploads PDF / arXiv ID
        │
        ▼
┌───────────────────────────────────────────────────┐
│           FastAPI backend (port 8000)              │
│                                                     │
│  routes/ → services/ → repositories/ → Supabase    │
└──────────────────────┬──────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────┐
│           core/agents — extraction pipeline         │
│                                                     │
│  Phase 1 (sequential): StructureAgent               │
│  Phase 2 (parallel):   EntityAgent, ResultsAgent,    │
│                        FigureAgent, ReasoningAgent   │
│  Phase 3 (sequential): SummaryAgent, ComparisonAgent │
└──────────────────────┬──────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────┐
│      core/graph — LangGraph summarisation engine     │
│                                                     │
│  map sections → extract entities/results (parallel) │
│    → synthesize → grade (retry once if weak)        │
│  Gemini → Groq → Ollama auto-failover                │
└──────────────────────┬──────────────────────────────┘
                        │
                        ▼
             Supabase PostgreSQL + pgvector
                        │
                        ▼
             React frontend (port 3000)
```

The LangGraph engine (`core/graph/`) is the **only** summarisation path. The
legacy template fallback in `core/agents/summary_agent.py` has been removed: it
assembled plausible-looking prose whenever the LLM was unreachable, which is
indistinguishable from a real summary once persisted. `SummaryAgent` is now a
thin adapter over the graph, and raises when summarisation fails.

---

## Repository Structure

```
PaperMind/
├── CLAUDE.md                     # This file
├── README.md
├── requirements.txt               # Root Python deps
├── requirements-dev.txt           # pytest, rouge-score — dev/test/eval only
├── docker-compose.yml             # api + web + redis (+ optional workers profile)
├── docs/                          # TESTING.md, BENCHMARKS.md, assets/
├── evals/run_benchmark.py         # full-pipeline benchmark against real PDFs
├── setups/                        # one-shot PowerShell setup scripts (Windows)
│
├── backend/
│   ├── main_app.py                # create_app() — composition root: settings,
│   │                               #   logging, middleware, routers. Nothing else
│   │                               #   should wire dependencies.
│   ├── main.py                    # Legacy PDF-extraction classes (AdvancedSectionExtractor,
│   │                               #   EnhancedEntityExtractor, ResultsExtractor,
│   │                               #   FigureExtractor) — still imported by core/agents/*
│   │                               #   as fallbacks. Not dead code.
│   ├── requirements.txt
│   ├── setup_database.py          # Supabase schema initialization script
│   │
│   ├── config/settings.py         # Typed pydantic-settings — single source for every
│   │                               #   env var. Reads backend/.env via `env_file=`, but
│   │                               #   that only populates the Settings object, NOT
│   │                               #   os.environ — see Configuration gotcha below.
│   ├── db/client.py                # SupabaseProvider (lazy, thread-safe) + LazySupabase
│   ├── repositories/               # ALL persistence. base.py, summary_repository.py,
│   │                               #   user_repository.py (User/Activity/Stats)
│   ├── services/                   # ALL business rules. auth_service, summary_service,
│   │                               #   arxiv_service — no FastAPI or Supabase imports,
│   │                               #   so they unit-test with plain fakes.
│   ├── api/
│   │   ├── deps.py                 # DI wiring — every repo/service as a FastAPI Depends
│   │   ├── errors.py               # AppError hierarchy + handlers → one JSON envelope
│   │   ├── middleware.py           # RequestContext (X-Request-ID) + SecurityHeaders
│   │   ├── rate_limit.py           # Named limit buckets, per-user keying
│   │   ├── health.py               # /api/health, /health/live, /health/ready
│   │   └── logging_config.py       # structlog; JSON in prod, console in dev
│   │
│   ├── routes/                     # HTTP-only concerns; delegate to services/
│   │   ├── process_paper.py        # /api/process/upload, /api/process/arxiv
│   │   ├── summaries.py            # /api/summaries CRUD
│   │   ├── search.py               # /api/search — arXiv keyword search
│   │   ├── profile.py              # /api/profile/*, avatar upload
│   │   ├── knowledge_graph.py      # /api/graph/* (semantic search, recommendations)
│   │   ├── corpus.py               # /api/corpus/* (topic clusters, citation network,
│   │   │                           #   author graph, contradiction map)
│   │   ├── feedback.py             # /api/feedback/* (star ratings)
│   │   ├── collections.py          # /api/collections/* (paper folders)
│   │   ├── batch_compare.py        # /api/batch/compare (cross-paper comparison)
│   │   ├── reading_queue.py        # /api/queue/* (reading list, priority scoring)
│   │   ├── annotations.py          # /api/annotations/* (highlights/notes)
│   │   ├── intelligence.py         # /api/intelligence/* (peer review, research gaps)
│   │   ├── export_extra.py         # /api/export/slides/{id} (HTML deck)
│   │   └── arxiv_diff.py           # /api/arxiv-diff/* (version-to-version diffing)
│   ├── auth/
│   │   ├── routes.py                # /api/auth/signup, /login, /logout, /me (GET+PUT),
│   │   │                           #   /change-password, /forgot-password, /reset-password
│   │   └── utils.py                 # JWT create/decode, bcrypt hash/verify
│   ├── database/
│   │   ├── config.py                # JWT_SECRET_KEY etc., re-exported from config/settings.py
│   │   ├── schema.sql                # Core tables: users, summaries, user_activity
│   │   ├── experience_schema.sql     # Agent cross-paper learning tables
│   │   └── migrations/               # Incremental SQL migrations, run in order
│   ├── tasks/paper_tasks.py         # Celery async task definitions
│   └── uploads/, arxiv_papers/      # Gitignored runtime scratch dirs (empty on a
│                                    #   fresh checkout; repopulated at runtime)
│
├── core/
│   ├── agent_integration.py         # AgentPaperProcessor wrapper, run_agent_mode()
│   ├── agents/                      # BaseAgent ABC, message_bus, orchestrator,
│   │                                #   structure/entity/results/figure/reasoning/
│   │                                #   summary/comparison agents, plus ablation_parser,
│   │                                #   reproducibility, and research_gap agents
│   ├── graph/                       # ⭐ LangGraph summarisation engine
│   │   ├── summary_graph.py         #   map-reduce StateGraph
│   │   ├── schemas.py               #   domain-agnostic Pydantic output schemas
│   │   ├── relation_agent.py        #   paper-to-paper relationship labelling
│   │   └── adapter.py               #   converts graph output to the legacy shape
│   ├── intelligence/                 # On-demand analysis, triggered from the UI's
│   │                                #   Intelligence tab, not part of the main pipeline:
│   │                                #   peer_review_agent, lit_review_agent,
│   │                                #   hypothesis_agent, hallucination_guard,
│   │                                #   confidence_service, slide_generator
│   ├── knowledge/                    # embedding_service (all-MiniLM-L6-v2),
│   │                                #   citation_extractor, graph_service,
│   │                                #   lineage_service, comparison_service,
│   │                                #   semantic_scholar_service, arxiv_diff_service,
│   │                                #   github_service, topic_clustering
│   ├── llm/
│   │   ├── providers.py              # Gemini → Groq → Ollama auto-failover chain
│   │   └── llm_interface.py          # Legacy LocalLLM (used by the non-graph path)
│   ├── memory/experience_db.py       # ExperienceStore: cross-paper learning in Supabase
│   └── pipeline/
│       ├── pdf_extractor.py          # MinerU → pymupdf4llm → PyMuPDF fallback chain
│       ├── text_cleaner.py           # Post-processing (hyphenation, fragments)
│       ├── diagram_processor.py      # Figure/diagram handling
│       └── processing_cache.py       # Redis SHA256 cache for PDF processing results
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js               # API proxy → localhost:8000
│   ├── tailwind.config.js           # Design tokens mapped to Tailwind names
│   └── src/
│       ├── App.jsx                   # Routes: /, /login, /signup, /forgot-password,
│       │                            #   /reset-password, /dashboard, /summary/:id,
│       │                            #   /batch, /profile, /timeline, /explore, /discover
│       ├── lib/api.js                # The single HTTP client — relative URLs, bearer
│       │                            #   token attached automatically, normalised errors
│       ├── contexts/
│       │   ├── AuthContext.jsx       # JWT token management, user state
│       │   ├── ThemeContext.jsx      # Light/dark toggle, drives the `.dark` class
│       │   └── ToastContext.jsx
│       ├── pages/                    # One file per route (13 pages)
│       └── components/
│           ├── ui/primitives.jsx     # Button, Card, Input, Badge, StagePill, Tabs,
│           │                        #   EmptyState, ErrorState, PageHeader, Spinner, …
│           ├── Layout.jsx            # Header, nav rail, mobile drawer, footer
│           ├── KnowledgeGraph.jsx    # vis-network graph, themed via CSS custom props
│           ├── ComparisonTable.jsx, EntityDisplay.jsx, FiguresDisplay.jsx,
│           │   SectionSummaries.jsx, StarRating.jsx, PaperCard.jsx,
│           │   ProcessingModal.jsx, ActivityChart.jsx, FlowchartViewer.jsx,
│           │   KeywordCloud.jsx, AvatarUpload.jsx, Logo.jsx
│
└── tests/
    ├── conftest.py                   # Fixtures: mock Supabase, LLM, test PDF
    ├── unit/                          # citation extraction, text cleaning, embeddings,
    │                                 #   entity/structure agents, graph engine, summary
    │                                 #   quality — pure logic, no network
    ├── integration/                   # multi-agent pipeline wiring, knowledge-graph queries
    └── api/                            # FastAPI route contracts (auth, process, summaries,
                                        #   graph, and newer routes)
```

---

## Development Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- A free [Supabase](https://supabase.com) project
- A free LLM key — [Google AI Studio](https://aistudio.google.com/apikey) (Gemini)
  and/or [Groq](https://console.groq.com) — or [Ollama](https://ollama.com) for fully local
- Redis (optional — rate limiting and caching degrade to in-memory without it)

### 1. Backend

```bash
python -m venv venv
# Windows: .\venv\Scripts\Activate.ps1   |   macOS/Linux: source venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt

cp backend/.env.example backend/.env
# Fill in: SUPABASE_URL, SUPABASE_SERVICE_KEY, JWT_SECRET_KEY, and at least one
# of GOOGLE_API_KEY / GROQ_API_KEY (or leave both unset to use local Ollama)
```

Run the SQL in `backend/database/` via the Supabase SQL editor, in order:
`schema.sql` → `experience_schema.sql` → `migrations/001_*.sql` → … in filename order.

```bash
cd backend
python -m uvicorn main_app:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
# http://localhost:3000, proxies /api/* to http://localhost:8000 (see vite.config.js)
```

### 3. Ollama (optional local LLM)

```bash
ollama pull qwen2.5:3b                   # fast tier
ollama pull qwen2.5:7b-instruct-q4_K_M   # better quality, ~4.5GB, the practical
                                          #   ceiling on a 4GB GPU like an RTX 2050
ollama serve
```

### 4. Redis (optional — rate limiting, Celery, processing cache)

```bash
docker run -d -p 6379:6379 redis:alpine
```

Without Redis, `api/rate_limit.py` probes reachability at startup and falls
back to in-memory buckets with a logged warning — this is expected in local dev.

### 5. Celery worker (optional — async processing)

```bash
cd backend
celery -A tasks.paper_tasks worker --loglevel=info
```

### 6. Docker Compose (everything at once)

```bash
docker compose up --build
# → http://localhost:8080
```

---

## The Extraction & Summarisation Pipeline

| Stage | Where | What |
|-------|-------|------|
| `StructureAgent` | `core/agents/` — phase 1 (sequential) | PDF → sections dict, domain (`cv`/`nlp`/`ml`/`general`) |
| `EntityAgent`, `ResultsAgent`, `FigureAgent`, `ReasoningAgent` | `core/agents/` — phase 2 (parallel) | Entities, quantitative results, figures, claims |
| LangGraph engine | `core/graph/summary_graph.py` | map-reduce over every section → structured entities/results → synthesize → LLM-judge grade (retries once if weak) |
| `SummaryAgent` | `core/agents/summary_agent.py` | Thin adapter over the graph engine; raises rather than falling back to templates |
| `RelationAgent` | `core/graph/relation_agent.py` | Labels how papers relate (extends/replicates/contradicts/…) into `paper_lineage` |
| Intelligence agents | `core/intelligence/` | On-demand only, triggered from the UI: peer review simulation, research gaps, reproducibility score, slide export |

**Inter-agent communication** in the phase-1/2/3 pipeline uses `AgentMessageBus`
(priority queue). Agents can broadcast `CONFLICT` messages when disagreeing on
extracted values; the orchestrator resolves via voting.

---

## Database Schema

### Core Tables (`schema.sql`)

| Table | Purpose |
|-------|---------|
| `users` | Auth, profile, avatar |
| `summaries` | Paper summaries (JSONB `summary_data` stores full agent/graph output) |
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

### Additional Tables (later migrations)

| Table | Purpose |
|-------|---------|
| `summary_feedback` | 1–5 star ratings + comments |
| `collections`, `collection_papers` | User paper folders (M2M) |
| `paper_lineage` | Temporal/relational links, written by `RelationAgent` |

---

## API Reference

All authenticated routes take `Authorization: Bearer <jwt>`. Interactive docs
at `/api/docs` (disabled when `APP_ENV=production`).

### Auth
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/signup` | — | Create account |
| POST | `/api/auth/login` | — | Get JWT token |
| POST | `/api/auth/logout` | ✓ | Invalidate the session cookie, if used |
| GET/PUT | `/api/auth/me` | ✓ | Read / update the current profile |
| POST | `/api/auth/change-password` | ✓ | Change password while signed in |
| POST | `/api/auth/forgot-password` | — | Issue a reset token (always reports success) |
| POST | `/api/auth/reset-password` | — | Consume a reset token, set a new password |

### Paper Processing
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/process/upload` | ✓ | Upload PDF → process → save |
| POST | `/api/process/arxiv` | ✓ | arXiv ID → download → process → save |

### Summaries & Search
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/summaries` | ✓ | List with pagination + search |
| GET | `/api/summaries/{id}` | ✓ | Single summary |
| DELETE | `/api/summaries/{id}` | ✓ | Delete |
| GET | `/api/search` | ✓ | arXiv keyword search |
| GET | `/api/export/slides/{id}` | ✓ | 5-slide HTML deck |

### Knowledge Graph & Corpus
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/graph/paper/{id}` | ✓ | Paper's entity/paper graph |
| POST | `/api/graph/search` | ✓ | Semantic vector search |
| GET | `/api/graph/recommendations/{id}` | ✓ | Top-K similar papers |
| GET | `/api/corpus/topic-clusters` \| `/citation-network` \| `/author-graph` \| `/contradiction-map` | ✓ | Corpus-wide graphs |
| POST | `/api/corpus/relate-papers` | ✓ | Run `RelationAgent` across the library |

### Health
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/health` | — | Diagnostic (all dependencies) |
| GET | `/api/health/live` | — | Liveness — process is up |
| GET | `/api/health/ready` | — | Readiness — DB reachable (the only hard dependency) |

---

## Common Development Tasks

### Adding a New Agent (extraction pipeline)

1. Create `core/agents/my_agent.py` extending `BaseAgent`
2. Implement `async def process(self, input_data: Dict) -> Dict`
3. Register it in `core/agents/orchestrator.py`'s `ParallelAgentOrchestrator`
4. Add its output to `_aggregate_results()` in `orchestrator.py`

### Adding a New API Endpoint

1. Create or find the router in `backend/routes/`
2. Register it in `backend/main_app.py`'s `_include_routers()` with `app.include_router(router, prefix='/api', tags=[...])`
3. Put business logic in `backend/services/`, persistence in `backend/repositories/` — routes should stay thin
4. Depend on `CurrentUser` from `auth.dependencies` for protected routes

### Running Database Migrations

Run SQL files in order via the Supabase SQL editor, or:
```bash
psql $DATABASE_URL -f backend/database/migrations/00X_name.sql
```

### Running Tests

```bash
pip install -r requirements.txt -r backend/requirements.txt -r requirements-dev.txt
pytest tests/ -v                 # everything
pytest tests/unit/ -v            # pure-logic units only
pytest tests/api/ -v             # FastAPI route contracts only
pytest tests/ --cov=core --cov=backend   # with coverage
```

Beyond unit tests, `evals/run_benchmark.py` runs the full pipeline against
real arXiv PDFs and measures latency, extraction coverage, and summary
quality (ROUGE vs. each paper's abstract). See `docs/BENCHMARKS.md`.

### Changing the LLM Provider

```bash
# backend/.env
PAPERMIND_LLM_PROVIDER=auto      # gemini | groq | ollama | auto (orders by available keys)
PAPERMIND_LLM_BACKEND=groq       # legacy path's backend selector — keep in sync with the above
GOOGLE_API_KEY=...               # Gemini — most generous free tier, recommended primary
GROQ_API_KEY=gsk_...             # Groq — fast, but free tier is per-account (~6k TPM),
                                  #   shared across all users, so it doesn't scale alone
```

---

## Configuration

### ⚠️ `.env` values must be duplicated for `core/` — read this before debugging a silent LLM/config issue

`backend/config/settings.py` uses **pydantic-settings**, which reads
`backend/.env` into a typed `Settings` object. This is what FastAPI routes see
via `SettingsDep`.

Most of `core/` (predates that settings module) reads configuration via plain
`os.environ.get(...)` instead — the LLM backend selector, `PAPERMIND_USE_GRAPH`,
and provider API keys. **pydantic-settings reading `.env` does not populate
`os.environ`**, so without something bridging the two, `core/` code always sees
its hardcoded defaults (Ollama, legacy summariser) regardless of what `.env`
actually says — with no error, just silently wrong behavior.

`core/__init__.py` calls `load_dotenv(backend/.env)` at import time specifically
to fix this. If you add a new `os.environ`-read config value, either move it to
`config/settings.py` and thread it through explicitly, or make sure it's set in
`backend/.env` (not just assumed as a Settings-class default) so both read paths
agree.

### ⚠️ Use `structlog`, never stdlib `logging`

The project logs with keyword fields (`logger.warning("x_failed", error=str(e))`).
`logging.Logger.warning` rejects arbitrary kwargs with `TypeError`, so a module
that imports stdlib `logging` raises on **every error path** — turning a handled
failure into an unhandled one. This silently disabled the hallucination guard and
`ResearchGapAgent` entirely. Always `import structlog` +
`structlog.get_logger(__name__)`.

### ⚠️ `pymupdf4llm` corrupts table extraction process-wide

It runs `TOOLS.unset_quad_corrections(True)` at *import* time, altering character
geometry for the whole process; resetting the flag does not undo it. Table
detection therefore runs in a subprocess whenever `pymupdf4llm` is loaded — see
`core/pipeline/table_extractor.py`.

### Environment variables (`backend/.env`)

```bash
# Required
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
JWT_SECRET_KEY=your-random-256-bit-key

# App environment — "production" enforces a hard JWT secret check and disables
# /api/docs; also rejects a wildcard CORS origin.
APP_ENV=development

# LLM — see "Changing the LLM Provider" above
PAPERMIND_LLM_PROVIDER=gemini    # Gemini strongly recommended — Groq's free tier
                                  #   (~6k tokens/min) cannot fit a whole paper.
GOOGLE_API_KEY=...
GROQ_API_KEY=...

# Optional
REDIS_URL=redis://localhost:6379/0
SENTRY_DSN=https://...@sentry.io/X
```

---

## Key Architecture Decisions

- **Layered backend** (`routes → services → repositories → Supabase`): services
  import no FastAPI and no Supabase, so they unit-test with plain fakes.
- **LangGraph over the legacy template pipeline**: map-reduce reads the whole
  paper instead of the abstract + first ~1k tokens; falls back to the legacy
  path on error rather than failing the request.
- **Gemini → Groq → Ollama auto-failover**: free-tier LLM access with no
  single point of failure and a fully local option.
- **pgvector over a dedicated vector DB**: all data stays in Supabase, no
  extra service to run.
- **JSONB for `summary_data`**: flexible schema evolution without migrations
  for new agent/graph output fields.
- **DesignMD `cursor` design system** (frontend): warm-cream editorial canvas,
  hairline-only depth (no card shadows), display type pinned at weight 400,
  and a five-pastel "stage" palette used only to mark categories (summary
  levels, entity kinds, graph node types) — never as action colors. Tokens
  live in `frontend/src/index.css` and `frontend/tailwind.config.js`;
  components in `frontend/src/components/ui/primitives.jsx`.
