"""Failures must stay visible.

Every test here pins a path that used to degrade into plausible-looking output:
invented prose, a passing grade nobody computed, perfect grounding for unchecked
claims, an all-5s peer review. The pipeline is allowed to fail — it is not
allowed to fabricate, and it is not allowed to persist a fabrication as a real
result.
"""

import pytest


# ── The LLM layer must raise rather than invent prose ─────────────────────────

def test_llm_has_no_template_fallback():
    """The old `_generate_template` returned invented sentences about an unread
    paper on every exception, including free-tier 429s."""
    from core.llm import llm_interface

    assert not hasattr(llm_interface.LocalLLM, '_generate_template')
    assert issubclass(llm_interface.LLMUnavailableError, RuntimeError)


@pytest.mark.asyncio
async def test_llm_raises_when_no_backend_available(monkeypatch):
    """Nothing left to try must raise, not return an empty or invented string.

    The provider chain is stubbed out because `generate()` consults it before
    `self.backend`: on a machine with GOOGLE_API_KEY set, the chain answers and
    the backend flag never comes up. Stubbing it is what makes "no backend
    available" actually true here, rather than true only on a keyless CI box.
    """
    from core.llm.llm_interface import LocalLLM, LLMBackend, LLMUnavailableError

    llm = LocalLLM.__new__(LocalLLM)          # bypass __init__/backend probing
    llm.backend = LLMBackend.UNAVAILABLE
    llm.max_tokens = 512
    llm.temperature = 0.7

    async def no_providers(*_args, **_kwargs):
        return ''

    monkeypatch.setattr(llm, '_generate_via_providers', no_providers)

    with pytest.raises(LLMUnavailableError):
        await llm.generate('Summarize this paper.')


@pytest.mark.asyncio
async def test_llm_backend_error_propagates(monkeypatch):
    """A provider failure must surface, not become a summary."""
    from core.llm.llm_interface import LocalLLM, LLMBackend, LLMUnavailableError

    llm = LocalLLM.__new__(LocalLLM)
    llm.backend = LLMBackend.GROQ
    llm.model_name = 'test-model'
    llm.max_tokens = 512
    llm.temperature = 0.7
    llm._groq_client = None
    llm._openai_client = None

    with pytest.raises(LLMUnavailableError):
        await llm._generate_openai('prompt', None, 256, 0.7, client=None)


# ── The save gate must reject failures dressed as summaries ───────────────────

@pytest.mark.parametrize('summaries, label', [
    ({}, 'no summary at all'),
    ({'main': ''}, 'blank summary'),
    ({'main': 'Summary generation in progress'}, 'pending-job sentinel'),
    ({'main': 'Analysis complete. See extracted data for details.'}, 'template filler'),
    ({'main': 'This paper presents a novel approach to the problem. '
              'The method demonstrates improved performance over baselines.'},
     'fabricated template prose'),
    ({'main': 'Transformer good.'}, 'degenerate 2-word summary'),
])
def test_degenerate_summaries_are_rejected(summaries, label):
    from api.errors import UnprocessableError
    from services.paper_processing_service import _reject_degenerate_summary

    with pytest.raises(UnprocessableError):
        _reject_degenerate_summary({'summaries': summaries})


def test_real_summary_is_accepted():
    from services.paper_processing_service import _reject_degenerate_summary

    real = (
        'The paper introduces the Transformer, a sequence transduction architecture '
        'that replaces recurrence with self-attention. ' * 12
    )
    _reject_degenerate_summary({'summaries': {'main': real}})     # must not raise


def test_rejection_carries_pipeline_status():
    """The error should say which stage failed, not just that something did."""
    from api.errors import UnprocessableError
    from services.paper_processing_service import _reject_degenerate_summary

    status = {'entity': {'status': 'failed', 'error': 'RateLimitError: 429'}}
    with pytest.raises(UnprocessableError) as exc:
        _reject_degenerate_summary({'summaries': {}, 'pipeline_status': status})
    assert exc.value.details['pipeline_status'] == status


# ── The hallucination guard must fail closed ──────────────────────────────────

def test_guard_reports_unverified_not_grounded(monkeypatch):
    """Claiming similarity 1.0 for a claim that was never checked is worse than
    reporting nothing — a green badge on unchecked output actively misleads."""
    import core.knowledge.embedding_service as es
    from core.intelligence import hallucination_guard

    def _boom(*a, **kw):
        raise RuntimeError('embedding model unavailable')

    monkeypatch.setattr(es, 'batch_embed', _boom)

    out = hallucination_guard.verify_claims(
        ['BLEU improved by 2 points.'],
        {'results': 'We evaluated the system on the WMT 2014 translation benchmark.'},
    )

    assert len(out) == 1
    assert out[0]['grounded'] is None, 'unchecked claim must not report grounded=True'
    assert out[0]['best_similarity'] is None
    assert out[0]['unverified_reason']


def test_guard_reports_unverified_with_no_source_text():
    from core.intelligence import hallucination_guard

    out = hallucination_guard.verify_claims(['A claim.'], {})
    assert out[0]['grounded'] is None


def test_guard_actually_verifies_claims():
    """The real path must run. The previous implementation imported a class that
    does not exist in this project, so verification never executed at all."""
    from core.intelligence import hallucination_guard

    sections = {
        'results': (
            'The Transformer achieves 28.4 BLEU on the WMT 2014 English-to-German '
            'translation task, improving over the previous best results. '
            'Training took 3.5 days on eight P100 GPUs.'
        )
    }
    supported = 'The model reaches 28.4 BLEU on WMT 2014 English-to-German.'
    invented = 'The authors prove a new lower bound for quantum error correction.'

    out = hallucination_guard.verify_claims([supported, invented], sections)

    assert out[0]['grounded'] is True, 'a supported claim should verify'
    assert out[1]['grounded'] is False, 'an unsupported claim should be flagged'
    assert out[0]['source_section'] == 'results'
    # The threshold is only meaningful if the two classes are well separated;
    # assert the gap rather than a specific cutoff so re-tuning stays honest.
    assert out[0]['best_similarity'] - out[1]['best_similarity'] > 0.3


# ── The grader must not invent a passing score ────────────────────────────────

@pytest.mark.asyncio
async def test_ungraded_summary_has_no_score(monkeypatch):
    """When the judge call fails the summary is accepted, but `score` stays None
    so it never reaches the summaries.quality_score column as a real number."""
    from core.graph import summary_graph

    async def _fail(*a, **kw):
        return None

    monkeypatch.setattr(summary_graph, '_structured', _fail)

    # Long enough to clear MIN_SUMMARY_WORDS, so the judge is actually reached.
    long_enough = ' '.join(['word'] * (summary_graph.MIN_SUMMARY_WORDS + 50))
    state = {'synthesis': {'summary': long_enough}, 'digest_text': 'digest'}
    out = await summary_graph.grade(state)

    assert out['grade']['graded'] is False
    assert out['grade']['score'] is None
    assert out['grade']['faithful'] is None


@pytest.mark.asyncio
async def test_ungraded_result_does_not_retry(monkeypatch):
    """Retrying on an ungraded synthesis burns free-tier quota with no evidence
    it would help."""
    from core.graph import summary_graph

    state = {'grade': {'graded': False, 'score': None}, 'attempts': 1}
    assert summary_graph._route_after_grade(state) == 'done'


@pytest.mark.asyncio
async def test_weak_grade_still_retries():
    from core.graph import summary_graph

    state = {'grade': {'graded': True, 'score': 0.2}, 'attempts': 1}
    assert summary_graph._route_after_grade(state) == 'retry'


# ── Peer review must not fabricate a score card ───────────────────────────────

def test_unparseable_peer_review_raises():
    """The all-5s fallback was persisted and then served from cache forever."""
    from core.intelligence.peer_review_agent import (
        _parse_review, PeerReviewUnavailableError,
    )

    with pytest.raises(PeerReviewUnavailableError):
        _parse_review('The model rambled without returning JSON.')

    with pytest.raises(PeerReviewUnavailableError):
        _parse_review('{"novelty": 8, "soundness":}')      # malformed JSON


def test_partial_review_is_rejected_rather_than_rendered_blank():
    """Truncated output is recoverable in general, but not for a score card.

    The parser now salvages the complete prefix of a reply cut off at the token
    ceiling. That is right where every recovered item has value; here the
    missing half *is* the score card, and a card of undefined bars is what a
    reader saw the last time this was allowed through.
    """
    from core.intelligence.peer_review_agent import (
        _parse_review, PeerReviewUnavailableError,
    )

    with pytest.raises(PeerReviewUnavailableError):
        _parse_review('{"novelty": 7, "soundness": 6, "clarity": 5, "major_conc')


def test_valid_peer_review_parses():
    from core.intelligence.peer_review_agent import _parse_review

    parsed = _parse_review(
        'Here you go: {"novelty": 7, "soundness": 6, "clarity": 8, "significance": 5}'
    )
    assert parsed['novelty'] == 7
