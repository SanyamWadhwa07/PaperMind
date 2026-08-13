"""Core package for parallel multi-agent research paper analysis system."""

import sys
from pathlib import Path

from dotenv import load_dotenv

__version__ = "2.0.0"


def _load_backend_env() -> None:
    """Load backend/.env into the real process environment.

    `backend/config/settings.py` uses pydantic-settings, which reads `.env`
    into its own typed `Settings` object without touching `os.environ`. Most
    of `core/` predates that settings module and reads configuration (LLM
    backend, `PAPERMIND_USE_GRAPH`, provider API keys) via plain
    `os.environ.get(...)`, so without this those reads always miss and the
    pipeline silently falls back to defaults (Ollama, legacy summariser)
    regardless of what `.env` actually says.
    """
    env_path = Path(__file__).resolve().parent.parent / 'backend' / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=False)


_load_backend_env()


def _force_utf8_streams() -> None:
    """Make stdout/stderr tolerate non-ASCII text.

    Extracted paper text routinely contains characters like '◦', '−', and '≥'.
    On Windows the console defaults to cp1252, so logging any of them raises
    UnicodeEncodeError from inside the logging call — which surfaced as the
    LangGraph summariser "failing" and silently falling back to the legacy path.

    Applied at package import so CLI scripts, benchmarks, workers, and tests get
    it too, not just the API process.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (ValueError, OSError):
                # Stream is detached or replaced by a capture buffer; nothing to do.
                pass


_force_utf8_streams()
