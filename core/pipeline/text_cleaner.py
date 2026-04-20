"""PDF text post-processing pipeline.

Fixes common artifacts introduced during PDF-to-text conversion:
hyphenated line breaks, sentence fragmentation from multi-column layouts,
running headers/footers, unicode noise, and near-duplicate sentences.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict


def fix_hyphenation(text: str) -> str:
    """Rejoin words split across lines by a hyphen."""
    # e.g. "trans-\nformer" → "transformer"
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    # Remove soft hyphens (U+00AD) with or without trailing newline
    text = re.sub(r'\u00ad\n?', '', text)
    return text


def fix_sentence_fragmentation(text: str) -> str:
    """Join lines that continue a sentence rather than starting a new one.

    A line break is treated as a continuation if:
    - the previous line does NOT end with sentence-ending punctuation
    - the next line starts with a lowercase letter
    """
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if (i + 1 < len(lines)
                and line
                and not re.search(r'[.!?:;]\s*$', line)
                and lines[i + 1]
                and lines[i + 1][0].islower()):
            result.append(line + ' ' + lines[i + 1].lstrip())
            i += 2
        else:
            result.append(line)
            i += 1
    return '\n'.join(result)


def remove_page_artifacts(text: str) -> str:
    """Strip page numbers and repeating short running headers/footers.

    Short lines (≤ 6 words) that appear identically more than twice are
    considered headers/footers and removed.
    """
    lines = text.split('\n')

    # Count short line occurrences
    from collections import Counter
    short_lines = [l.strip() for l in lines if l.strip() and len(l.split()) <= 6]
    counts = Counter(short_lines)
    noise = {line for line, cnt in counts.items() if cnt > 2}

    # Remove bare page numbers and noisy short lines
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r'\d{1,4}', stripped):
            continue
        if stripped in noise:
            continue
        cleaned.append(line)

    return '\n'.join(cleaned)


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/tabs and normalize unicode punctuation."""
    # Normalize unicode (smart quotes, em-dashes, etc.)
    text = unicodedata.normalize('NFKC', text)
    # Replace unicode hyphens/dashes with ASCII
    text = re.sub(r'[\u2010\u2011\u2012\u2013\u2014\u2015]', '-', text)
    # Collapse multiple whitespace (but preserve newlines)
    text = re.sub(r'[ \t]+', ' ', text)
    # Remove trailing spaces on each line
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    # Collapse 3+ blank lines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def deduplicate_sentences(text: str, threshold: float = 0.85) -> str:
    """Remove near-duplicate sentences using SequenceMatcher.

    Keeps the first occurrence when two sentences have similarity ≥ threshold.
    """
    # Split into sentences (naive but fast — avoids heavy NLP dependencies)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    kept: list[str] = []
    for candidate in sentences:
        candidate = candidate.strip()
        if not candidate:
            continue
        duplicate = any(
            SequenceMatcher(None, candidate, s).ratio() >= threshold
            for s in kept
        )
        if not duplicate:
            kept.append(candidate)
    return ' '.join(kept)


def clean_section(text: str) -> str:
    """Apply the full cleaning pipeline to a single section's text."""
    if not text:
        return text
    text = fix_hyphenation(text)
    text = fix_sentence_fragmentation(text)
    text = remove_page_artifacts(text)
    text = normalize_whitespace(text)
    text = deduplicate_sentences(text)
    return text


def clean_all_sections(sections: Dict[str, str]) -> Dict[str, str]:
    """Clean every section in the sections dict returned by StructureAgent."""
    return {key: clean_section(value) for key, value in sections.items()}
