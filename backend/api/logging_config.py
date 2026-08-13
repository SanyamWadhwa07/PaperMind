"""Structured logging setup.

Development gets colourised key-value console output; production emits JSON so
logs are queryable in whatever aggregator sits downstream.
"""

from __future__ import annotations

import logging
import sys

import structlog

from config import Settings


def configure_logging(settings: Settings) -> None:
    # Windows consoles default to cp1252 and raise UnicodeEncodeError on the
    # bullets and arrows that appear in extracted paper text.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (ValueError, OSError):  # pragma: no cover - detached streams
                pass

    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(format='%(message)s', stream=sys.stdout, level=level)

    # These libraries log a line per HTTP call, which drowns everything else.
    for noisy in ('httpx', 'httpcore', 'hpack', 'urllib3'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt='iso', utc=True),
    ]

    use_json = settings.log_json or settings.is_production
    renderer = (
        structlog.processors.JSONRenderer()
        if use_json
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
