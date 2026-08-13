<div align="center">

<img src="docs/assets/banner.svg" alt="PaperMind" width="100%"/>

<br/>

[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1C3C3C?style=flat)](https://langchain-ai.github.io/langgraph/)
[![Supabase](https://img.shields.io/badge/Supabase-pgvector-3ECF8E?style=flat&logo=supabase&logoColor=white)](https://supabase.com/)
[![LLMs](https://img.shields.io/badge/LLM-Gemini%20·%20Groq%20·%20Ollama-D9A86C?style=flat)](#-llm-provider-chain)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat)](LICENSE)

**Turn academic PDFs into faithful, structured intelligence — full-paper summaries, typed entities, results tables, and a knowledge graph of how papers relate.**

</div>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [What makes it different](#-what-makes-it-different)
- [Architecture](#️-architecture)
- [The summarization engine](#-the-summarization-engine)
- [LLM provider chain](#-llm-provider-chain)
- [Quick start](#-quick-start)
- [Configuration](#️-configuration)
- [API reference](#-api-reference)
- [Testing & benchmarks](#-testing--benchmarks)
- [Deployment](#-deployment)
- [Project structure](#-project-structure)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🌟 Overview

**PaperMind** turns research papers into structured, trustworthy insight. Upload a PDF or paste an arXiv ID and it reads the **whole** paper through a [LangGraph](https://langchain-ai.github.io/langgraph/) map-reduce pipeline, then returns:

- 📝 a **~900-word analysis** grounded in the full text, plus separate **method** and **experimental-setup** write-ups
- 🔑 **key findings, contributions, limitations & future work** — findings carry real numbers, not "improves performance"
- 🧬 **domain-agnostic typed entities** — *methods · materials · measurements · tools* (biomedicine, physics, ML… not just CS)
- 📊 **real tables lifted out of the PDF** — ruled *and* borderless — rendered as tables, and read by the model for results
- 🖼️ **figure images** extracted, stored, and shown alongside their captions
- 🧾 **per-section digests** covering the whole paper
- 🕸️ a **knowledge graph** linking papers by AI-derived relationships (extends / replicates / contradicts / shares-method …)

It runs entirely on **free LLM tiers** (Gemini → Groq) with a **local Ollama** fallback, so there are no API costs to get started.

---

## ✨ What makes it different

Most summarizers paste an abstract into one prompt. PaperMind is built like a production AI system:

| | Typical summarizer | PaperMind |
|---|---|---|
| **Coverage** | abstract + first ~1k tokens | the **whole paper** in one pass (map-reduce only when it won't fit) |
| **Extraction** | hard-coded ML regex (BERT, ImageNet…) | **LLM structured output**, domain-agnostic |
| **Tables** | ignored | **ruled *and* borderless** tables lifted out and rendered |
| **Results** | regex over text | LLM reading **prose + the extracted tables** |
| **Length** | a paragraph | ~**900-word** analysis + separate method and setup sections |
| **Failure** | silently returns something | **fails loudly**; nothing fabricated is ever stored |
| **Reliability** | single model | **Gemini → Groq → Ollama** auto-failover |
| **Relations** | cosine similarity number | **RelationAgent** explains *how* papers relate |

### Honest by construction

The hard rule: **PaperMind never presents a failure as a result.** A run that
can't reach an LLM raises instead of returning invented prose; a summary that
comes back degenerate is rejected rather than saved; a claim that couldn't be
checked reports `grounded: null`, not `true`; an ungraded summary has **no**
quality score rather than a plausible one. Every stage records `ok` / `failed`
into `summary_data.pipeline_status`, so an empty section is always
distinguishable from a broken one.

---

## 🏗️ Architecture

<div align="center">
<img src="docs/assets/architecture.svg" alt="PaperMind architecture" width="100%"/>
</div>

```
React (Vite)  ──/api──▶  FastAPI  ──▶  LangGraph engine  ──▶  Supabase (pgvector)
                                          │
                            Gemini → Groq → Ollama (auto-failover)
```

---

## 🧠 The summarization engine

The engine ([`core/graph/summary_graph.py`](core/graph/summary_graph.py)) is a LangGraph `StateGraph`:

```
START → prepare ─┬─ fits?  ──▶ read_paper ────────────────┐
                 └─ too long ─▶ map_sections ─┬─▶ entities ┤
                                              └─▶ results ─┴─▶ synthesize → grade ──▶ END
                                                                          └──(retry if weak)
```

1. **prepare** — clean sections, **strip the bibliography**, measure the paper, and pick a strategy.
2. **read_paper** *(single pass)* — **one** call sees the entire paper and returns every section digest, the typed entities, and every quantitative result together.
3. **map_sections + extract_*** *(fallback)* — section-by-section, for papers too large for the provider's budget.
4. **synthesize** — ~900-word analysis plus `methods_detail`, `experimental_setup`, findings, contributions, limitations, future work (smart tier).
5. **grade** — an LLM judge scores faithfulness & specificity; a weak result loops back once. If the judge itself fails, the summary is kept but marked **ungraded** — it never receives a fabricated score.

**Why single-pass matters.** Free tiers meter *requests* far more tightly than
context, so one large call is cheaper than a dozen small ones — about **3 LLM
calls per paper instead of ~16**. It is also more accurate: a model that sees the
whole paper can tie a number in a table to the method that produced it, which
per-section calls structurally cannot do. A failed single-pass read falls back to
map-reduce rather than losing the paper.

> ⚠️ **Schema field order is load-bearing.** Models emit structured fields in
> declaration order and stop at `max_tokens`. In `PaperReading`, the compact
> `entities` and `results` are declared *before* the long `sections` list — with
> `sections` first, it consumed the whole budget and both came back empty.

**RelationAgent** ([`core/graph/relation_agent.py`](core/graph/relation_agent.py)) labels how papers relate and writes typed edges into `paper_lineage`, which the knowledge-graph endpoints render.

---

## 🔌 LLM provider chain

A single env-driven chain, defined in [`core/llm/providers.py`](core/llm/providers.py):

| Provider | Role | Why |
|----------|------|-----|
| **Gemini** (`gemini-flash-latest`) | primary | 1M-token context, most generous free tier |
| **Groq** (`llama-3.3-70b` / `llama-3.1-8b-instant`) | overflow | ultra-fast, free |
| **Ollama** (`qwen2.5:7b`/`3b`) | offline fallback | private, $0, runs locally |

`PAPERMIND_LLM_PROVIDER=auto` orders by available keys; a named provider becomes primary with the rest as fallbacks. On a failure or rate-limit the chain cascades automatically.

**Gemini is strongly recommended as primary.** Groq's free tier allows ~6,000
tokens *per minute*, which is less than a single paper — so it is used for
map-reduce fragments, not whole-paper reads. The per-provider budget lives in
`_CONTEXT_BUDGET_CHARS` and decides which strategy a paper gets.

> Model IDs use **rolling aliases** (`gemini-flash-latest`) rather than pinned
> versions. Google retires numbered models on a rolling basis — `gemini-2.0-flash`
> and the entire 2.5 line now return 404 — and because the chain treats any error
> as "try the next provider", a retired pin degrades output *silently*. Pin a
> version with `PAPERMIND_GEMINI_SMART_MODEL` if you need reproducibility, and
> check liveness with:
>
> ```bash
> curl 'localhost:8000/api/health?probe_llm=true'   # actually calls each provider
> ```

> **Local model sizing (e.g. RTX 2050, 4 GB):** `qwen2.5:3b` runs fully on-GPU; `qwen2.5:7b-instruct-q4_K_M` (~4.5 GB) is the practical ceiling and spills a few layers to CPU. The 7B is markedly more reliable at structured extraction.

---

## 🚀 Quick start

### Prerequisites
- Python 3.10+ · Node.js 18+
- A free [Supabase](https://supabase.com) project
- A free LLM key — [Google AI Studio](https://aistudio.google.com/apikey) (Gemini) and/or [Groq](https://console.groq.com) — **or** [Ollama](https://ollama.com) for fully local

### 1 — Backend

```bash
python -m venv venv
# Windows: .\venv\Scripts\Activate.ps1   |   macOS/Linux: source venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
cp backend/.env.example backend/.env   # then fill in the values (see Configuration)
cd backend && uvicorn main_app:app --reload --port 8000
```

### 2 — Database
Run the SQL in [`backend/database/`](backend/database/) via the Supabase SQL editor, in order:
`schema.sql` → `experience_schema.sql` → `migrations/001` … `migrations/009`.

### 3 — Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000  (proxies /api → :8000)
```

### 4 — (optional) Local LLM

```bash
ollama pull qwen2.5:3b        # fast tier
ollama pull qwen2.5:7b-instruct-q4_K_M   # better quality
ollama serve
```

---

## ⚙️ Configuration

Key `backend/.env` values (full list in [`.env.example`](backend/.env.example)):

```env
# Supabase
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
JWT_SECRET_KEY=<64-char-random>

# Summarization engine
PAPERMIND_LLM_PROVIDER=gemini         # gemini | groq | ollama | auto
                                      # Gemini strongly recommended: Groq's free
                                      # tier (~6k tokens/min) can't fit a paper.

# Free LLM keys (use either / both; Ollama needs none)
GOOGLE_API_KEY=...                    # Gemini  (recommended primary)
GROQ_API_KEY=gsk_...                  # Groq

# Free-tier safety
PAPERMIND_LLM_CONCURRENCY=2           # cap simultaneous calls
PAPERMIND_LLM_MAX_RETRIES=6           # backoff retries for 429s
```

> ⚠️ Groq's free tier is **per-account** (≈6k tokens/min, shared across all users), so it won't scale to a multi-user deployment on its own — set `GOOGLE_API_KEY` to make **Gemini** the primary for hosted use.

---

## 📡 API reference

All authenticated routes take `Authorization: Bearer <jwt>`. Interactive docs at `/api/docs`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/signup` · `/login` · `/logout` · `GET /me` | Auth |
| `POST` | `/api/auth/forgot-password` · `/reset-password` | Password reset |
| `POST` | `/api/process/upload` · `/api/process/arxiv` | Process a paper |
| `GET`  | `/api/summaries` · `/api/summaries/{id}` | List / fetch summaries |
| `GET`  | `/api/graph/paper/{id}` · `/recommendations/{id}` | Per-paper graph |
| `GET`  | `/api/corpus/citation-network` · `/author-graph` | Corpus graphs |
| `POST` | `/api/corpus/relate-papers` | **Run RelationAgent across the library** |
| `GET`  | `/api/health` · `/health/live` · `/health/ready` | Liveness / readiness / dependency health |

Interactive docs at `/api/docs` (disabled automatically when `APP_ENV=production`).

---

## 🧪 Testing & benchmarks

Unit, integration, and API-contract tests across `core/` + `backend/`. CI runs
the full suite with coverage on every push — see
[`.github/workflows/tests.yml`](.github/workflows/tests.yml) and
[`docs/TESTING.md`](docs/TESTING.md) for the current pass count and coverage
percentage.

```bash
pip install -r requirements.txt -r backend/requirements.txt -r requirements-dev.txt
pytest tests/ --cov=core --cov=backend
```

Beyond unit tests, [`evals/run_benchmark.py`](evals/run_benchmark.py) runs the
**full 10-agent pipeline against real arXiv papers** (not fixtures) and
measures latency, parallel speedup, extraction coverage, and summary quality
(ROUGE vs. each paper's own abstract). Full results and methodology in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) — headline numbers:

> ⚠️ **The published benchmark numbers predate the current pipeline and are being
> re-measured.** The old harness scored `success = bool(summary_text)`, so two
> two-word summaries counted toward a "100% success rate". It now requires real
> content (minimum length, no placeholder text) and reports a failure reason —
> so the next run's success rate will be lower *and* meaningful.

Current end-to-end behaviour, measured on real arXiv papers (ML, LLM, and
particle-physics), all values from the live pipeline:

| Metric | Value |
|---|---|
| Summary length | **600–970 words** + method/setup sections |
| Quantitative results extracted | **18–34 rows/paper**, sourced from the real tables |
| Tables detected | **3–4/paper**, with captions |
| Section digests | **12–24/paper** (whole-paper coverage) |
| LLM calls per paper | **~3** (down from ~16) |
| End-to-end latency | **~2–4 min/paper** on free tiers |
| Entities / figures extracted | **13 / 8.5** per paper (median) |

Building the benchmark surfaced and fixed a real bug: the legacy figure
extractor was silently producing 0 usable figures per paper — see
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md#what-this-benchmark-caught) for the
root cause and fix.

---

## 🚢 Deployment

### Docker Compose (self-hosted, single command)

```bash
docker compose up --build     # → http://localhost:8080
```

Brings up `api` (FastAPI + Gunicorn/Uvicorn workers), `web` (nginx serving the
built frontend, proxying `/api`), and `redis` (rate limiting + the processing
cache, which lets a re-uploaded PDF skip the pipeline entirely). See
[`docker-compose.yml`](docker-compose.yml), [`backend/Dockerfile`](backend/Dockerfile),
and [`frontend/Dockerfile`](frontend/Dockerfile).

### Split across managed services (free tiers)

| Layer | Host | Notes |
|-------|------|-------|
| Frontend | **Vercel** | `npm run build`, output `dist/` |
| Backend | **Render** | `uvicorn main_app:app --host 0.0.0.0 --port $PORT` |
| Database | **Supabase** | managed Postgres + pgvector |
| LLM | **Gemini/Groq** free tiers | no GPU needed in the cloud |

Point the frontend at the backend and restrict `CORS_ORIGINS` to your deployed
origin in `backend/.env` — `main_app.py` reads it from `config/settings.py`,
which refuses to boot with a wildcard origin when `APP_ENV=production`.

---

## 📁 Project structure

```
PaperMind/
├── backend/
│   ├── main_app.py            # create_app() composition root — routers, health, CORS
│   ├── config/settings.py     # typed pydantic-settings — single source for every env var
│   ├── db/client.py           # SupabaseProvider (lazy, thread-safe)
│   ├── repositories/          # ALL persistence — routes never touch Supabase directly
│   ├── services/               # ALL business rules — auth, summary, arxiv
│   ├── api/                   # DI wiring, error envelope, rate limiting, request logging
│   ├── routes/                # process_paper, summaries, corpus, graph, …
│   ├── auth/                  # JWT creation/validation + FastAPI dependency
│   └── database/migrations/   # 001 … run in order via the Supabase SQL editor
├── core/
│   ├── graph/                 # ⭐ LangGraph engine
│   │   ├── summary_graph.py   #   single-pass / map-reduce StateGraph
│   │   ├── schemas.py         #   domain-agnostic Pydantic schemas
│   │   ├── relation_agent.py  #   paper-to-paper RelationAgent
│   │   └── adapter.py         #   legacy-format adapter
│   ├── pipeline/
│   │   ├── pdf_extractor.py   #   PdfBackend protocol: MinerU → pymupdf4llm → fitz
│   │   ├── table_extractor.py #   ruled + borderless table detection
│   │   ├── metadata_extractor.py  # title/authors from page-1 layout
│   │   └── processing_cache.py    # Redis SHA-256 cache of processed PDFs
│   ├── llm/providers.py       # Gemini→Groq→Ollama chain
│   ├── agents/                # orchestrator + extraction agents
│   ├── intelligence/          # on-demand: peer review, lit review, research gaps,
│   │                          #   reproducibility scoring, hallucination guard, slides
│   ├── knowledge/             # graph, citations, semantic scholar
│   └── pipeline/pdf_extractor.py  # MinerU → pymupdf4llm → fitz
├── frontend/src/
│   ├── pages/                 # one file per route
│   ├── components/ui/         # design-system primitives (Button, Card, Tabs, …)
│   └── contexts/              # auth, toast, theme
└── docs/assets/              # banner.svg · architecture.svg
```

---

## 🤝 Contributing

1. Fork & branch (`git checkout -b feature/x`)
2. Keep Python PEP-8, run the frontend build (`npm run build`) before PRs
3. Conventional commits (`feat:`, `fix:`, `docs:`)
4. Open a PR describing the change

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

**Built by [@SanyamWadhwa07](https://github.com/SanyamWadhwa07)** · powered by LangGraph + free LLM tiers

[⬆ Back to top](#-table-of-contents)

</div>
