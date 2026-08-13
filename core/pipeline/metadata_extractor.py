"""Paper metadata (title, authors) recovered from page-1 layout.

Kept separate from section extraction because it answers a different question
and is derived from the raw PDF rather than from any one backend's output — so
the same values come back whichever extractor wins.

Every function here returns empty values rather than guesses. A placeholder
title is indistinguishable from a real one once persisted, which is how every
uploaded PDF ended up stored as "Research Paper".
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger(__name__)


# Junk titles that PDF producers write into document metadata.
_BAD_META_TITLE = re.compile(
    r"^(untitled|microsoft word|document\d*|paper|manuscript|arxiv|preprint|\d+)\b|\.(doc|docx|tex|pdf|dvi)$",
    re.IGNORECASE,
)

# A plausible personal name: 2–5 capitalised words, optional initials/particles.
# The leading class spans Latin-1 Supplement *and* Latin Extended-A/B so names
# like 'Łukasz' or 'Šimon' aren't silently dropped.
_UPPER = r"[A-ZÀ-ÖØ-ÞĀ-ɏ]"
_NAME_RE = re.compile(
    rf"^{_UPPER}[\w'’\-]*(?:\.)?(?:\s+(?:van|von|de|del|della|der|den|di|da|dos|la|le|bin|al))?"
    rf"(?:\s+{_UPPER}[\w'’\-]*\.?){{1,4}}$"
)

_AUTHOR_SPLIT_RE = re.compile(r"\s*(?:,|;|\band\b|&|\*|†|‡|\d)\s*")

_STOP_AT_RE = re.compile(r"\b(abstract|introduction|keywords|index terms)\b", re.IGNORECASE)

# Preprint server stamps sit in the page margin in large rotated type and would
# otherwise outrank the real title.
_MARGIN_STAMP_RE = re.compile(r"\b(arxiv|biorxiv|medrxiv|ssrn|hal-|doi:|preprint)\b", re.IGNORECASE)

# Affiliations parse as plausible names ('Google Brain'), so they need excluding.
_ORG_RE = re.compile(
    r"\b(universit|institut|college|school|department|dept|laborator|labs?|research|"
    r"academy|hospital|clinic|center|centre|foundation|corp|inc\b|ltd\b|gmbh|"
    r"google|microsoft|meta|facebook|amazon|apple|nvidia|openai|deepmind|ibm|intel|"
    r"brain\b|technolog|science|engineering|faculty|campus)",
    re.IGNORECASE,
)


# Affiliation markers: ASCII '*' plus the Unicode variants papers actually use
# (U+2217 ASTERISK OPERATOR, daggers, superscript digits).
_AFFIL_MARK_RE = re.compile(r"[\d\*∗†‡§¶†-‧¹²³⁰-₟]+")


def _clean_author(raw: str) -> str:
    """Strip affiliation markers and whitespace from one author candidate."""
    raw = _AFFIL_MARK_RE.sub("", raw)                 # affiliation superscripts
    raw = re.sub(r"\([^)]*\)", "", raw)               # parenthesised affiliations
    return re.sub(r"\s+", " ", raw).strip(" ,;.")


def extract_title_authors(pdf_path: str) -> tuple[str, List[str]]:
    """Recover the paper's title and author list from page 1 layout.

    Uses font size rather than position: on essentially every paper the title is
    the largest text in the upper part of page 1. Falls back to embedded PDF
    metadata when layout analysis is inconclusive.

    Returns ``("", [])`` when nothing trustworthy is found — never a placeholder.
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        return "", []

    title, authors = "", []
    try:
        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            return "", []
        page = doc[0]
        page_height = page.rect.height or 1.0

        lines: List[Dict[str, Any]] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:      # 0 = text
                continue
            for line in block.get("lines", []):
                spans = line.get("spans") or []
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue
                # Skip rotated text — arXiv/bioRxiv stamps run vertically up the
                # margin in large type and would otherwise outrank the title.
                direction = line.get("dir", (1.0, 0.0))
                if abs(direction[1]) > 0.01:
                    continue
                lines.append({
                    "text": text,
                    "size": round(max(s.get("size", 0) for s in spans), 1),
                    "y": line.get("bbox", [0, 0, 0, 0])[1],
                })

        # Title: largest font in the top 45% of the page, excluding page furniture.
        head = [
            l for l in lines
            if l["y"] < page_height * 0.45
            and len(l["text"]) > 3
            and not _STOP_AT_RE.search(l["text"])
            and not _MARGIN_STAMP_RE.search(l["text"])
        ]
        if head:
            max_size = max(l["size"] for l in head)
            title_lines = [l for l in head if l["size"] >= max_size - 0.6]
            title_lines.sort(key=lambda l: l["y"])
            title = re.sub(r"\s+", " ", " ".join(l["text"] for l in title_lines)).strip()
            if not (10 <= len(title) <= 300):
                title = ""

            # Authors: lines below the title, above the abstract, that parse as names.
            if title_lines:
                title_bottom = max(l["y"] for l in title_lines)
                for l in sorted(lines, key=lambda l: l["y"]):
                    if l["y"] <= title_bottom or l["size"] >= max_size - 0.6:
                        continue
                    if _STOP_AT_RE.search(l["text"]):
                        break
                    if "@" in l["text"] or "http" in l["text"].lower():
                        continue
                    candidates = [_clean_author(p) for p in _AUTHOR_SPLIT_RE.split(l["text"])]
                    found = [
                        c for c in candidates
                        if _NAME_RE.match(c) and not _ORG_RE.search(c)
                    ]
                    if found:
                        authors.extend(found)
                    if len(authors) >= 30:
                        break

        # Fall back to embedded metadata only when layout gave us nothing usable.
        if not title:
            meta_title = (doc.metadata or {}).get("title", "") or ""
            meta_title = re.sub(r"\s+", " ", meta_title).strip()
            if 10 <= len(meta_title) <= 300 and not _BAD_META_TITLE.search(meta_title):
                title = meta_title

        doc.close()
    except Exception as exc:
        logger.debug("title_extraction_failed", error=str(exc))
        return "", []

    # De-duplicate, preserving order.
    seen: set = set()
    unique_authors = [a for a in authors if not (a.lower() in seen or seen.add(a.lower()))]
    return title, unique_authors


