"""Guard against stdlib `logging.getLogger(...)` module loggers in core/ and backend/.

This project logs with structlog, keyword fields and all — `logger.warning("x_failed",
error=str(e))`. `logging.Logger.warning` rejects arbitrary kwargs with `TypeError`, so a
module that binds a stdlib logger raises on *every* error path it logs from, turning a
handled failure into an unhandled one.

This has already happened twice: once in `core/intelligence/hallucination_guard.py` and
`core/agents/research_gap_agent.py` (documented in CLAUDE.md as "silently disabled"), and
again in `core/agents/structure_agent.py`, which raised on exactly the papers that needed
its legacy-extractor fallback — the fallback line was unreachable. A comment in CLAUDE.md
was not enough to stop it recurring, so this test exists to make it impossible to merge.

If a new module has a genuine reason to use stdlib `logging` (configuring the root logger,
or wrapping a legacy file where every call site is provably `%s`-style/f-string with no
keyword arguments), add it to `_ALLOWLIST` with a comment explaining why — not by disabling
this test.
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCAN_DIRS = ('core', 'backend')

# Directories that are never source we own or that legitimately live outside the rule.
_EXCLUDED_DIR_PARTS = {
    '__pycache__', '.git', 'venv', 'node_modules', 'migrations', 'tests', 'uploads',
    'arxiv_papers',
}

_ALLOWLIST = {
    # Configures the stdlib root logger and third-party loggers as part of setting up
    # structlog itself — this is infrastructure, not application logging, and cannot be
    # done through structlog.get_logger().
    'backend/api/logging_config.py',
    # Legacy PDF-extraction fallback (CLAUDE.md: "still imported by core/agents/* as
    # fallbacks. Not dead code."). Every one of its ~40 logger call sites is a single
    # positional f-string or `%s`-style argument — never a structlog-style keyword — so
    # the TypeError this test guards against cannot occur here. Converting a legacy file
    # untouched by this QA pass to structlog is a larger, riskier change than the bug
    # this test targets; revisit if the file is ever refactored for other reasons.
    'backend/main.py',
}


def _iter_python_files():
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.is_dir():
            continue
        for path in base.rglob('*.py'):
            if any(part in _EXCLUDED_DIR_PARTS for part in path.relative_to(REPO_ROOT).parts):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in _ALLOWLIST:
                continue
            yield path, rel


def _binds_stdlib_logger(tree: ast.Module) -> list[int]:
    """Return line numbers where `<name> = logging.getLogger(...)` is assigned.

    Only counts `getLogger` calls made through a name that stdlib `import logging`
    (optionally aliased) actually bound — so `structlog.get_logger` and unrelated
    `.getLogger()` calls on other objects don't false-positive.
    """
    logging_aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'logging':
                    logging_aliases.add(alias.asname or alias.name)

    if not logging_aliases:
        return []

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == 'getLogger'
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id in logging_aliases
        ):
            hits.append(node.lineno)
    return hits


def test_no_stdlib_logger_bindings_in_core_and_backend():
    offenders = {}
    for path, rel in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=rel)
        except SyntaxError:
            continue
        lines = _binds_stdlib_logger(tree)
        if lines:
            offenders[rel] = lines

    assert not offenders, (
        "The following modules bind a stdlib `logging.getLogger(...)` logger. This "
        "project logs with structlog keyword fields, which raises TypeError on a stdlib "
        "logger. Switch to `import structlog` / `logger = structlog.get_logger(__name__)`, "
        "or add the file to `_ALLOWLIST` above with a reason:\n" + "\n".join(
            f"  {rel}:{lines}" for rel, lines in sorted(offenders.items())
        )
    )
