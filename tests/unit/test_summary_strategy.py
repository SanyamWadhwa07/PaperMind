"""Reading-strategy selection, reference stripping, and the single-pass fallback.

These cover the decisions the graph makes *before* and *around* the LLM calls,
which is where the token budget is won or lost and where a silent fallback would
otherwise be invisible.
"""

import pytest

from core.graph import summary_graph as sg


# ── Reference stripping ───────────────────────────────────────────────────────

def test_strip_references_removes_trailing_bibliography():
    body = "We evaluate on WMT 2014. " * 40
    text = body + "\nReferences\n[1] Vaswani et al. 2017.\n[2] Devlin et al. 2019.\n"
    out = sg.strip_references(text)
    assert "Vaswani" not in out
    assert "WMT 2014" in out


def test_strip_references_ignores_early_mention():
    """'References' near the top is a cross-reference, not the bibliography."""
    text = "See References for details. " + ("Our method works as follows. " * 60)
    assert sg.strip_references(text) == text


@pytest.mark.parametrize("heading", ["Bibliography", "REFERENCES", "Works Cited", "3. References"])
def test_strip_references_matches_common_headings(heading):
    body = "Body text that carries the paper. " * 40
    assert "[1]" not in sg.strip_references(f"{body}\n{heading}\n[1] Someone 2020.\n")


def test_usable_sections_drops_boilerplate():
    sections = {
        "introduction": "We introduce a new method. " * 20,
        "references": "[1] Someone. [2] Another.",
        "acknowledgements": "We thank our funders. " * 20,
        "conclusion": "We conclude the method works. " * 20,
    }
    names = [n for n, _ in sg.usable_sections(sections)]
    assert "introduction" in names and "conclusion" in names
    assert "references" not in names and "acknowledgements" not in names


def test_usable_sections_drops_stubs():
    sections = {"introduction": "Real content here. " * 20, "figures": "Fig 1."}
    assert [n for n, _ in sg.usable_sections(sections)] == ["introduction"]


def test_usable_sections_orders_by_priority():
    """Ordering matters: when a budget forces a cut, the tail is dropped."""
    sections = {
        "conclusion": "c " * 100,
        "introduction": "i " * 100,
        "abstract": "a " * 100,
        "method": "m " * 100,
    }
    assert [n for n, _ in sg.usable_sections(sections)][:2] == ["abstract", "introduction"]


# ── Strategy selection ────────────────────────────────────────────────────────

def _sections(char_count: int) -> dict:
    return {"introduction": "x" * char_count}


def test_short_paper_reads_in_one_pass(monkeypatch):
    monkeypatch.setattr(sg, "context_budget_chars", lambda: 400_000)
    state = sg.prepare({"sections": _sections(30_000)})
    assert state["single_pass"] is True
    assert sg._route_after_prepare(state) == "single_pass"


def test_paper_over_budget_falls_back_to_map_reduce(monkeypatch):
    """Groq's free tier meters tokens per minute, so a whole paper won't fit."""
    monkeypatch.setattr(sg, "context_budget_chars", lambda: 24_000)
    state = sg.prepare({"sections": _sections(200_000)})
    assert state["single_pass"] is False
    assert sg._route_after_prepare(state) == "map_reduce"


def test_tables_count_against_the_budget(monkeypatch):
    """Tables are sent with the paper, so they must be measured with it."""
    monkeypatch.setattr(sg, "context_budget_chars", lambda: 20_000)
    state = sg.prepare({"sections": _sections(15_000), "tables_md": ["y" * 10_000]})
    assert state["single_pass"] is False


def test_empty_paper_does_not_take_single_pass(monkeypatch):
    monkeypatch.setattr(sg, "context_budget_chars", lambda: 400_000)
    assert sg.prepare({"sections": {}})["single_pass"] is False


# ── Single-pass fallback ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_single_pass_read_falls_back(monkeypatch):
    """A failed whole-paper read must not lose the paper."""
    async def _fail(*a, **kw):
        return None

    monkeypatch.setattr(sg, "_structured", _fail)
    out = await sg.read_paper({"paper_text": "some paper", "tables_md": []})

    assert out["single_pass"] is False
    assert sg._route_after_read(out) == "map_reduce"


def test_successful_read_proceeds_to_synthesis():
    state = {"digests": [{"section": "intro", "summary": "text", "facts": []}]}
    assert sg._route_after_read(state) == "synthesize"


# ── Digest assembly ───────────────────────────────────────────────────────────

def test_digest_text_includes_sections_and_facts():
    digests = [
        {"section": "model_architecture", "summary": "It uses attention.",
         "facts": ["6 layers", "8 heads"]},
    ]
    text = sg._build_digest_text(digests)
    assert "Model Architecture" in text
    assert "It uses attention." in text
    assert "- 6 layers" in text


def test_digest_text_respects_extraction_limit(monkeypatch):
    monkeypatch.setattr(sg, "EXTRACTION_CHAR_LIMIT", 50)
    digests = [{"section": "s", "summary": "x" * 500, "facts": []}]
    assert len(sg._build_digest_text(digests)) <= 50
