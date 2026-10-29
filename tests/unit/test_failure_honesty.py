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


# ── The guard must be WIRED IN, not merely correct ────────────────────────────
#
# The guard's own docstring records that it once imported a class this project
# never defined, so its failure path was the only path that ever ran. It was then
# fixed — and left with no production call site at all, which is the same bug
# wearing a different hat: `README.md` advertised claim-level groundedness that
# nothing computed. Correctness tests could not catch that, because the function
# passed them in isolation. These two do.

def test_guard_has_a_production_call_site():
    """`verify_claims` must be reachable from shipped code, not just from tests.

    A guard that nothing calls is indistinguishable from a guard that does not
    exist, except that it reads as a feature to anyone auditing the repo.
    """
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    callers = []
    for directory in ('core', 'backend'):
        for path in (repo_root / directory).rglob('*.py'):
            if any(part in {'__pycache__', 'venv', 'node_modules'} for part in path.parts):
                continue
            if path.name == 'hallucination_guard.py':      # the definition itself
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == 'verify_claims':
                    callers.append(str(path.relative_to(repo_root)))
                elif isinstance(node, ast.Attribute) and node.attr == 'verify_claims':
                    callers.append(str(path.relative_to(repo_root)))

    assert callers, (
        'hallucination_guard.verify_claims has no call site in core/ or backend/. '
        'It is dead code, and any documentation claiming per-claim groundedness '
        'is unsupported.'
    )


def test_graph_routes_the_accepted_synthesis_through_verify():
    """Grounding must sit on the path a shipped summary actually takes."""
    from core.graph import summary_graph

    graph = summary_graph.get_summary_graph()
    assert 'verify' in graph.get_graph().nodes, 'verify node missing from the graph'

    # It must hang off `grade`'s accept branch, so it sees the final text and
    # runs once — not off `synthesize`, which a retry can discard.
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ('grade', 'verify') in edges, f'grade does not route into verify: {sorted(edges)}'


async def test_verify_node_grounds_real_claims_and_flags_invented_ones():
    from core.graph.summary_graph import verify

    state = {
        'sections': {
            'results': (
                'The Transformer achieves 28.4 BLEU on the WMT 2014 English-to-German '
                'translation task, improving over the previous best results by over two '
                'BLEU. Training took 3.5 days on eight P100 GPUs, a small fraction of the '
                'training costs reported for the best models from the literature.'
            ),
        },
        'synthesis': {
            'key_findings': ['The model reaches 28.4 BLEU on WMT 2014 English-to-German.'],
            'contributions': ['The authors prove a new lower bound for quantum error correction.'],
        },
    }

    out = await verify(state)
    claims = out['claims']

    assert len(claims) == 2
    assert claims[0]['grounded'] is True
    assert claims[1]['grounded'] is False
    assert claims[0]['source_section'] == 'results'


async def test_verify_node_never_fails_the_run():
    """A completed summary must survive a broken guard."""
    import core.intelligence.hallucination_guard as guard
    from core.graph.summary_graph import verify

    original = guard.verify_claims
    guard.verify_claims = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('boom'))
    try:
        out = await verify({
            'sections': {'results': 'x' * 300},
            'synthesis': {'key_findings': ['A claim.']},
        })
    finally:
        guard.verify_claims = original

    assert out == {'claims': []}


async def test_verify_node_ignores_the_bibliography():
    """A claim matching a *cited* paper's title is not grounded in this paper."""
    from core.graph.summary_graph import verify

    state = {
        'sections': {
            'references': (
                'Kingma and Ba. Adam: A Method for Stochastic Optimization. ICLR 2015. '
                'He et al. Deep Residual Learning for Image Recognition. CVPR 2016. '
                'Devlin et al. BERT: Pre-training of Deep Bidirectional Transformers. 2019.'
            ),
        },
        'synthesis': {'key_findings': ['We introduce deep residual learning for image recognition.']},
    }

    out = await verify(state)
    # The only source text was a bibliography, which usable_sections() drops — so
    # there is nothing legitimate to verify against and the claim is unverifiable,
    # NOT grounded.
    assert out['claims'][0]['grounded'] is None


# ── The numeric rule ──────────────────────────────────────────────────────────
#
# Measuring the guard against the labelled claims in evals/golden/ showed cosine
# similarity classifying close negatives at chance: accuracy 0.500 at every
# threshold from 0.05 to 0.50. "…reaches 28.4 BLEU" and "…reaches 31.7 BLEU" are
# near-identical sentences, so they are near-identical vectors — the falsehood
# lives in one digit, which contributes almost nothing to an embedding. No
# threshold fixes that, so a deterministic numeric rule sits in front.

def test_a_fabricated_number_is_caught_however_similar_the_sentence_reads():
    from core.intelligence import hallucination_guard

    sections = {'results': (
        'The Transformer achieves 28.4 BLEU on the WMT 2014 English-to-German '
        'translation task. Training took 3.5 days on eight P100 GPUs.'
    )}
    real = 'The model achieves 28.4 BLEU on WMT 2014 English-to-German.'
    fabricated = 'The model achieves 31.7 BLEU on WMT 2014 English-to-German.'

    out = hallucination_guard.verify_claims([real, fabricated], sections)

    assert out[0]['grounded'] is True
    assert out[1]['grounded'] is False, 'a swapped number must not pass'
    assert out[1]['rule'] == 'numeric'
    assert '31.7' in out[1]['unsupported_numbers']

    # The point of the rule: similarity alone would have passed both.
    assert out[1]['best_similarity'] >= hallucination_guard.SIMILARITY_THRESHOLD


def test_the_offending_number_is_named_so_the_flag_is_actionable():
    from core.intelligence import hallucination_guard

    out = hallucination_guard.verify_claims(
        ['Training required 400 GPU-days on the benchmark corpus described above.'],
        {'results': 'Training took 3.5 days on eight P100 GPUs for the base configuration.'},
    )
    assert out[0]['unsupported_numbers'] == ['400']


def test_extractor_mangled_decimals_do_not_read_as_hallucinations():
    """pymupdf4llm renders "28.4" in prose as "28 _._ 4". Without normalisation
    the guard would flag every correctly-extracted decimal as invented."""
    from core.intelligence import hallucination_guard

    out = hallucination_guard.verify_claims(
        ['The model reaches 28.4 BLEU on the English-to-German translation task.'],
        {'results': 'establishing a new state-of-the-art BLEU score of 28 _._ 4 on the task.'},
    )
    assert out[0]['grounded'] is True, out[0]


def test_claims_without_numbers_fall_through_to_the_semantic_rule():
    from core.intelligence import hallucination_guard

    out = hallucination_guard.verify_claims(
        ['The authors prove a new lower bound for quantum error correction.'],
        {'results': 'The Transformer relies entirely on attention mechanisms for translation.'},
    )
    assert out[0]['rule'] == 'semantic'
    assert out[0]['grounded'] is False


def test_years_alone_do_not_trigger_the_numeric_rule():
    """A year appears in nearly every paper, so requiring it to match adds no
    evidence and would cost recall."""
    from core.intelligence import hallucination_guard

    out = hallucination_guard.verify_claims(
        ['The work was evaluated on a translation benchmark released in 1997.'],
        {'results': 'The Transformer relies entirely on attention mechanisms for translation.'},
    )
    assert out[0]['rule'] == 'semantic'
