"""Citation extractor — parses reference sections from academic PDFs.

Extracts structured citation data from the raw reference text preserved
by AdvancedSectionExtractor under the '__references__' key.
"""

from __future__ import annotations
import re
import structlog
from typing import List, Dict, Optional

logger = structlog.get_logger(__name__)

# Common reference entry starters: [1], 1., Author et al., etc.
_REF_SPLIT = re.compile(
    r'(?:^|\n)\s*(?:\[\d+\]|\d{1,3}\.)\s+',
    re.MULTILINE
)
_ARXIV_ID = re.compile(r'(\d{4}\.\d{4,5}(?:v\d+)?)')
_YEAR = re.compile(r'\b(19|20)\d{2}\b')
_AUTHORS_STRIP = re.compile(r'^[A-Z][a-z]+(?:,?\s+[A-Z]\.?)+(?:\s+and\s+[A-Z][a-z]+(?:,?\s+[A-Z]\.?)*)?')


def extract_citations(reference_text: str) -> List[Dict]:
    """Parse raw reference text into a list of structured citation dicts."""
    if not reference_text or len(reference_text.strip()) < 20:
        return []

    # Split into individual reference entries
    entries = [e.strip() for e in _REF_SPLIT.split(reference_text) if e.strip()]
    citations = []
    for entry in entries[:200]:  # hard cap to avoid runaway
        citation = _parse_single_entry(entry)
        if citation:
            citations.append(citation)
    return citations


def _parse_single_entry(text: str) -> Optional[Dict]:
    """Extract fields from a single bibliography entry."""
    if len(text) < 15:
        return None

    arxiv_match = _ARXIV_ID.search(text)
    year_match = _YEAR.search(text)

    # Heuristic title: text between first comma-cluster and year (or end of line)
    title = _extract_title_heuristic(text)

    return {
        'raw': text[:400],
        'cited_arxiv_id': arxiv_match.group(1) if arxiv_match else None,
        'cited_title': title,
        'year': int(year_match.group()) if year_match else None,
        'cited_authors': _extract_authors(text),
        'confidence': 0.8 if arxiv_match else 0.5,
    }


def _extract_title_heuristic(text: str) -> Optional[str]:
    """Guess the title from a reference entry (between authors and venue/year)."""
    # Look for text in double quotes or after year
    quoted = re.search(r'["\u201c](.{10,200}?)["\u201d]', text)
    if quoted:
        return quoted.group(1).strip()
    # Fallback: first long "phrase" that looks like a title (title case or sentence)
    parts = [p.strip() for p in text.split('.') if 10 < len(p.strip()) < 200]
    for part in parts[1:3]:
        if re.search(r'[A-Z]', part):
            return part
    return None


def _extract_authors(text: str) -> List[str]:
    """Extract author names from the start of a reference entry."""
    # Match "Lastname, F. and Lastname, F." patterns at start
    match = _AUTHORS_STRIP.match(text)
    if match:
        raw = match.group()
        # Split on ' and ' or ';'
        names = re.split(r'\s+and\s+|;\s*', raw)
        return [n.strip() for n in names if n.strip()][:6]
    return []


def extract_citation_contexts(full_text: str, citations: List[Dict]) -> List[Dict]:
    """Find in-text citation contexts (sentences containing [N] or (Author, year))."""
    sentences = re.split(r'(?<=[.!?])\s+', full_text)
    for citation in citations:
        raw = citation.get('raw', '')
        arxiv_id = citation.get('cited_arxiv_id')
        contexts = []

        # Look for numeric citations [1]-style
        for sent in sentences:
            if re.search(r'\[\d+\]', sent) or (arxiv_id and arxiv_id in sent):
                contexts.append(sent[:300])
                if len(contexts) >= 2:
                    break

        citation['citation_contexts'] = contexts
    return citations


def match_arxiv_ids_to_library(
    citations: List[Dict],
    supabase_client,
    user_id: str
) -> List[Dict]:
    """Cross-reference extracted arXiv IDs against the user's paper library."""
    arxiv_ids = [c['cited_arxiv_id'] for c in citations if c.get('cited_arxiv_id')]
    if not arxiv_ids:
        return citations

    try:
        result = supabase_client.table('summaries') \
            .select('id, arxiv_id, paper_title') \
            .eq('user_id', user_id) \
            .in_('arxiv_id', arxiv_ids) \
            .execute()

        id_map = {row['arxiv_id']: row['id'] for row in (result.data or [])}
        for c in citations:
            if c.get('cited_arxiv_id') in id_map:
                c['matched_summary_id'] = id_map[c['cited_arxiv_id']]
    except Exception as e:
        logger.warning("arxiv_id_match_failed", error=str(e))

    return citations
