<div align="center">

<img src="docs/assets/banner.svg" alt="PaperMind" width="100%"/>

<br/>

[![Tests](https://github.com/SanyamWadhwa07/PaperMind/actions/workflows/tests.yml/badge.svg)](.github/workflows/tests.yml)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1C3C3C?style=flat)](https://langchain-ai.github.io/langgraph/)
[![Supabase](https://img.shields.io/badge/Supabase-pgvector-3ECF8E?style=flat&logo=supabase&logoColor=white)](https://supabase.com/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat)](LICENSE)

**Read a paper once. Keep what it said, what it measured, and how it relates to everything else you've read.**

</div>

---

## Contents

- [What it does](#what-it-does)
- [How it differs from a summarizer](#how-it-differs-from-a-summarizer)
- [Architecture](#architecture)
- [The summarization engine](#the-summarization-engine)
- [LLM provider chain](#llm-provider-chain)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Testing and benchmarks](#testing-and-benchmarks)
- [Deployment](#deployment)
- [Project structure](#project-structure)
- [License](#license)

---

## What it does

Give PaperMind a PDF or an arXiv ID. It reads the entire paper through a
[LangGraph](https://langchain-ai.github.io/langgraph/) pipeline and gives back:

- A roughly 900-word analysis grounded in the full text, with separate method
  and experimental-setup write-ups.
- Key findings, contributions, limitations and future work. The findings carry
  the actual numbers rather than "improves performance".
- Typed entities that are not hardcoded to machine learning. Methods,
  materials, measurements and tools, so a biology or physics paper produces
  something useful instead of empty lists.
- Tables lifted out of the PDF, ruled and borderless alike, rendered as tables
  and read by the model when it extracts results.
- Figure images, extracted and stored next to their captions.
- Per-section digests covering the whole paper.
- A knowledge graph connecting papers by what the model worked out about them:
  extends, replicates, contradicts, shares-method.

Beyond the summary there is an intelligence layer you invoke on demand. It
covers simulated peer review, reproducibility scoring, research-gap detection,
a state-of-the-art lookup that finds newer work on the same topic, and a slide
deck export.

Everything runs on free LLM tiers, Gemini first and Groq second, with local
Ollama behind them, so there is nothing to pay for to try it.

---

## How it differs from a summarizer

Most tools paste an abstract into one prompt and return a paragraph.

| | Typical summarizer | PaperMind |
|---|---|---|
| **Coverage** | abstract + first ~1k tokens | the whole paper in one pass; map-reduce only when it will not fit |
| **Extraction** | regex tuned to ML names | LLM structured output, domain-agnostic |
| **Tables** | ignored | ruled and borderless tables lifted out and rendered |
| **Results** | regex over prose | the model reads prose *and* the extracted tables |
| **Output** | a paragraph | ~900-word analysis plus method and setup sections |
| **On failure** | returns something anyway | raises; nothing invented is ever stored |
| **Reliability** | one model | Gemini → Groq → Ollama failover |
| **Relations** | a similarity score | RelationAgent explains *how* two papers relate |

### Failure is never dressed up as a result

A run that cannot reach an LLM raises instead of returning invented prose. A
summary that comes back degenerate is rejected rather than saved. A claim that
could not be checked reports `grounded: null` rather than `true`. An ungraded
summary carries no quality score at all instead of a plausible-looking one.
Every stage writes `ok` or `failed` into `summary_data.pipeline_status`, so an
empty section stays distinguishable from a broken one.

There is no template fallback behind the summarizer, and that absence is
deliberate. A template can always produce something that reads like a summary,
which is exactly the problem: once that text reaches the database, nothing can
separate it from a real one.

---

## Architecture

<div align="center">
<img src="docs/assets/architecture.svg" alt="PaperMind architecture" width="100%"/>
</div>

```
React (Vite)  ──/api──▶  FastAPI  ──▶  LangGraph engine  ──▶  Supabase (pgvector)
                                          │
                            Gemini → Groq → Ollama (auto-failover)
```

The backend is layered `routes → services → repositories → Supabase`. Services
import neither FastAPI nor Supabase, so they unit-test against plain fakes.

---

## The summarization engine

The engine ([`core/graph/summary_graph.py`](core/graph/summary_graph.py)) is a
LangGraph `StateGraph`:

```
START → prepare ─┬─ fits?  ──▶ read_paper ────────────────┐
                 └─ too long ─▶ map_sections ─┬─▶ entities ┤
                                              └─▶ results ─┴─▶ synthesize → grade ──▶ END
                                                                          └──(retry if weak)
```

1. `prepare` cleans the sections, strips the bibliography, measures the paper
   and chooses a strategy.
2. `read_paper` is the single-pass route. One call sees the entire paper and
   returns the section digests, the typed entities and every quantitative
   result together.
3. `map_sections` with the `extract_*` nodes is the fallback, working section by
   section when a paper is too large for the provider's budget.
4. `synthesize` writes the long analysis, `methods_detail`, `experimental_setup`,
   findings, contributions, limitations and future work.
5. `grade` runs an LLM judge over faithfulness and specificity, and a weak
   result loops back once. If the judge itself fails, the summary is kept and
   marked ungraded rather than given an invented score.

Free tiers meter requests far more tightly than context, so one large call costs
less than a dozen small ones. That is roughly 3 LLM calls per paper instead of
about 16. Reading in one pass is also more accurate, because a model holding the
whole paper can connect a number in a table to the method that produced it, and
per-section calls cannot do that at all. When the single-pass read fails,
map-reduce picks the paper up instead of losing it.

> **Schema field order is load-bearing.** Models emit structured fields in
> declaration order and stop at `max_tokens`. In `PaperReading` the compact
> `entities` and `results` are declared *before* the long `sections` list. With
> `sections` first it consumed the entire budget and both of the others came
> back empty.

[`core/graph/relation_agent.py`](core/graph/relation_agent.py) labels how papers
relate and writes typed edges into `paper_lineage`, which the knowledge-graph
endpoints render.

---

## LLM provider chain

One env-driven chain, defined in [`core/llm/providers.py`](core/llm/providers.py):

| Provider | Role | Why |
|----------|------|-----|
| **Gemini** (`gemini-flash-latest`) | primary | 1M-token context, the most generous free tier |
| **Groq** (`llama-3.3-70b` / `llama-3.1-8b-instant`) | overflow | very fast, free |
| **Ollama** (`qwen2.5:7b` / `3b`) | offline fallback | private, local, no key |

`PAPERMIND_LLM_PROVIDER=auto` orders providers by which keys are present. Naming
one makes it primary and leaves the rest as fallbacks. The chain cascades on any
error or rate limit.

**Prefer Gemini as primary.** Groq's free tier allows about 6,000 tokens per
minute, which is smaller than one paper, so it serves map-reduce fragments
rather than whole-paper reads. Each provider's budget lives in
`_CONTEXT_BUDGET_CHARS` and decides which strategy a paper gets.

> Model IDs are **rolling aliases** (`gemini-flash-latest`) rather than pinned
> versions. Google retires numbered models on a rolling basis, and both
> `gemini-2.0-flash` and the whole 2.5 line now return 404. Since the chain
> treats any error as "try the next provider", a retired pin degrades output
> *silently*. Pin a version through `PAPERMIND_GEMINI_SMART_MODEL` when you need
> reproducibility, and check liveness with:
>
> ```bash
> curl 'localhost:8000/api/health?probe_llm=true'   # actually calls each provider
> ```

> **Sizing a local model** (RTX 2050, 4 GB): `qwen2.5:3b` runs entirely on the
> GPU. `qwen2.5:7b-instruct-q4_K_M` at ~4.5 GB is the practical ceiling and
> spills a few layers to CPU, but it is markedly more reliable at structured
> extraction.

---

## Quick start

### Prerequisites

- Python 3.10+, Node.js 18+
- A free [Supabase](https://supabase.com) project
- A free LLM key from [Google AI Studio](https://aistudio.google.com/apikey) or
  [Groq](https://console.groq.com), or [Ollama](https://ollama.com) to stay local

### 1. Backend

```bash
python -m venv venv
# Windows: .\venv\Scripts\Activate.ps1   |   macOS/Linux: source venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
cp backend/.env.example backend/.env   # then fill it in — see Configuration
cd backend && uvicorn main_app:app --reload --port 8000
```

### 2. Database

Run the SQL in [`backend/database/`](backend/database/) through the Supabase SQL
editor, in this order: `schema.sql`, `experience_schema.sql`, then everything in
`migrations/` in filename order.

Run the whole `migrations/` directory even on a fresh database. Several
migrations exist specifically to repair a partial run of
`experience_schema.sql`. That file declares its tables first and its views and
functions last, so a run that stops midway leaves the tables present and
everything below them missing, which then fails at the call site rather than at
install time.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000, proxies /api to :8000
```

### 4. Local LLM (optional)

```bash
ollama pull qwen2.5:3b                   # fast tier
ollama pull qwen2.5:7b-instruct-q4_K_M   # better quality
ollama serve
```

---

## Configuration

The important `backend/.env` values. Full list in
[`.env.example`](backend/.env.example):

```env
# Supabase
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
JWT_SECRET_KEY=<64-char-random>

# Summarization engine
PAPERMIND_LLM_PROVIDER=gemini         # gemini | groq | ollama | auto

# Free LLM keys — either or both; Ollama needs none
GOOGLE_API_KEY=...
GROQ_API_KEY=gsk_...

# Free-tier safety
PAPERMIND_LLM_CONCURRENCY=2           # cap simultaneous calls
PAPERMIND_LLM_MAX_RETRIES=6           # backoff retries on 429

# Optional
REDIS_URL=redis://localhost:6379/0    # rate limiting + PDF processing cache
SEMANTIC_SCHOLAR_API_KEY=             # removes the shared-pool 429s on Discover
```

> Groq's free tier is per-account, roughly 6k tokens per minute shared across
> every user of your deployment, so it will not carry a multi-user install on
> its own. Set `GOOGLE_API_KEY` to make Gemini primary for anything hosted.

### `core/` reads `os.environ`, not the settings object

`backend/config/settings.py` uses pydantic-settings, which loads `backend/.env`
into a typed `Settings` object without populating `os.environ`. Most of `core/`
predates that module and reads the environment directly, so `core/__init__.py`
calls `load_dotenv()` at import time to bridge the two. A new value that `core/`
reads from `os.environ` but that only exists as a `Settings` default will come
back as its hardcoded fallback, and nothing will report an error.

### Use `structlog`, never stdlib `logging`

The project logs keyword fields, as in `logger.warning("x_failed", error=str(e))`.
`logging.Logger.warning` rejects arbitrary kwargs with `TypeError`, so a module
that imports stdlib logging raises on every error path and converts a handled
failure into an unhandled one.

---

## API reference

Authenticated routes take `Authorization: Bearer <jwt>`. Interactive docs live at
`/api/docs`, disabled automatically when `APP_ENV=production`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/signup` · `/login` · `/logout` · `GET /me` | Auth |
| `POST` | `/api/auth/forgot-password` · `/reset-password` | Password reset |
| `POST` | `/api/process/upload` · `/api/process/arxiv` | Process a paper |
| `GET`  | `/api/summaries` · `/api/summaries/{id}` | List and fetch summaries |
| `GET`  | `/api/graph/paper/{id}` · `/recommendations/{id}` | Per-paper graph |
| `GET`  | `/api/graph/timeline` · `/ancestry/{id}` | Timeline and lineage |
| `GET`  | `/api/graph/discover` | Search Semantic Scholar, falling back to arXiv |
| `GET`  | `/api/corpus/citation-network` · `/author-graph` · `/topic-clusters` | Corpus graphs |
| `POST` | `/api/corpus/relate-papers` | Run RelationAgent across the library |
| `POST` | `/api/corpus/recompute-clusters` | Recluster the library by topic |
| `GET`  | `/api/intelligence/sota/{id}` | Newer state-of-the-art work on this topic |
| `GET`  | `/api/intelligence/gaps/{id}` · `/reproducibility/{id}` | On-demand analysis |
| `GET`  | `/api/health` · `/health/live` · `/health/ready` | Health, liveness, readiness |

---

## Testing and benchmarks

Unit, integration and API-contract tests across `core/` and `backend/`. CI runs
the suite with coverage on every push. See
[`.github/workflows/tests.yml`](.github/workflows/tests.yml) and
[`docs/TESTING.md`](docs/TESTING.md).

```bash
pip install -r requirements.txt -r backend/requirements.txt -r requirements-dev.txt
pytest tests/ --cov=core --cov=backend
```

[`evals/run_benchmark.py`](evals/run_benchmark.py) runs the full pipeline against
real arXiv papers rather than fixtures, measuring latency, parallel speedup,
extraction coverage and summary quality (ROUGE against each paper's own
abstract). Methodology and full results are in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

> **The published benchmark numbers predate the current pipeline and are being
> re-measured.** The old harness scored `success = bool(summary_text)`, so two
> two-word summaries counted toward a "100% success rate". It now requires real
> content and reports a failure reason, so the next run's success rate will be
> both lower and meaningful.

Measured end-to-end on real arXiv papers across ML, LLM and particle physics:

| Metric | Value |
|---|---|
| Summary length | 600–970 words, plus method and setup sections |
| Quantitative results extracted | 18–34 rows per paper, from the real tables |
| Tables detected | 3–4 per paper, with captions |
| Section digests | 12–24 per paper |
| LLM calls per paper | ~3, down from ~16 |
| End-to-end latency | 2–4 min per paper on free tiers |
| Entities / figures | 13 / 8.5 per paper (median) |

Writing the benchmark caught a real bug: the legacy figure extractor was
silently producing zero usable figures per paper. Root cause and fix are in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md#what-this-benchmark-caught).

---

## Deployment

### Docker Compose

```bash
docker compose up --build     # http://localhost:8080
```

Brings up `api` (FastAPI behind Uvicorn workers), `web` (nginx serving the built
frontend and proxying `/api`), and `redis`, which backs rate limiting and the
processing cache that lets a re-uploaded PDF skip the pipeline entirely. Both
Redis-backed features degrade to in-memory when it is absent.

Paper processing runs synchronously inside the request, which is why the `api`
service sets a long timeout. There is no worker service.

### Split across managed free tiers

| Layer | Host | Notes |
|-------|------|-------|
| Frontend | Vercel | `npm run build`, output `dist/` |
| Backend | Render | `uvicorn main_app:app --host 0.0.0.0 --port $PORT` |
| Database | Supabase | managed Postgres with pgvector |
| LLM | Gemini / Groq free tiers | no GPU needed |

Point the frontend at the backend and restrict `CORS_ORIGINS` to your deployed
origin. `config/settings.py` refuses to boot on a wildcard origin when
`APP_ENV=production`.

---

## Project structure

```
PaperMind/
├── backend/
│   ├── main_app.py            # create_app() composition root — routers, health, CORS
│   ├── config/settings.py     # typed pydantic-settings, single source for every env var
│   ├── db/client.py           # SupabaseProvider (lazy, thread-safe)
│   ├── repositories/          # all persistence; routes never touch Supabase directly
│   ├── services/              # all business rules — auth, summary, arxiv
│   ├── api/                   # DI wiring, error envelope, rate limiting, request logging
│   ├── routes/                # process_paper, summaries, corpus, graph, intelligence, …
│   ├── auth/                  # JWT creation and validation, FastAPI dependency
│   └── database/migrations/   # run in filename order via the Supabase SQL editor
├── core/
│   ├── graph/                 # the LangGraph engine
│   │   ├── summary_graph.py   #   single-pass / map-reduce StateGraph
│   │   ├── schemas.py         #   domain-agnostic Pydantic schemas
│   │   ├── relation_agent.py  #   paper-to-paper relationship labelling
│   │   └── adapter.py         #   legacy-format adapter
│   ├── pipeline/
│   │   ├── pdf_extractor.py   #   PdfBackend protocol: MinerU → pymupdf4llm → fitz
│   │   ├── table_extractor.py #   ruled and borderless table detection
│   │   ├── metadata_extractor.py  # title and authors from page-1 layout
│   │   └── processing_cache.py    # Redis SHA-256 cache of processed PDFs
│   ├── llm/providers.py       # the Gemini → Groq → Ollama chain
│   ├── agents/                # orchestrator and the extraction agents
│   ├── intelligence/          # on demand: peer review, research gaps,
│   │                          #   reproducibility, hallucination guard, slides
│   ├── knowledge/             # graph, citations, embeddings, paper search
│   └── memory/                # cross-paper experience store
├── frontend/src/
│   ├── pages/                 # one file per route
│   ├── components/ui/         # design-system primitives
│   └── contexts/              # auth, toast, theme
├── evals/run_benchmark.py     # full-pipeline benchmark against real PDFs
└── docs/                      # TESTING.md, BENCHMARKS.md, assets/
```

---

## License

MIT. See [LICENSE](LICENSE).

---

<div align="center">

Built by [@SanyamWadhwa07](https://github.com/SanyamWadhwa07)

[Back to top](#contents)

</div>
