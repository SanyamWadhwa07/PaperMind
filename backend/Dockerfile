# syntax=docker/dockerfile:1.7
#
# PaperMind API image.
#
# Multi-stage: wheels are built once in `builder` against the toolchain, then
# only the resulting site-packages are copied into a slim runtime that carries
# no compilers. Keeps the final image small and its attack surface narrow.

# ── Stage 1: build dependencies ───────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build-only toolchain. Never lands in the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt backend/requirements.txt ./
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/backend \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production

# Runtime-only shared libraries. PyMuPDF needs libgl/libglib for rasterisation.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Run unprivileged: a container escape should not land on root.
RUN groupadd --system --gid 1001 papermind \
    && useradd --system --uid 1001 --gid papermind --create-home papermind

WORKDIR /app

COPY --chown=papermind:papermind backend/ ./backend/
COPY --chown=papermind:papermind core/ ./core/

RUN mkdir -p /app/uploads /app/arxiv_papers \
    && chown -R papermind:papermind /app/uploads /app/arxiv_papers

USER papermind

EXPOSE 8000

# Liveness only — readiness is a separate endpoint the orchestrator polls.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health/live || exit 1

WORKDIR /app/backend

# Workers are CPU-bound on PDF extraction; override WEB_CONCURRENCY per host.
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "uvicorn main_app:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
