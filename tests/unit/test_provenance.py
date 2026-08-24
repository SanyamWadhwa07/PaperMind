"""Run provenance: what actually produced a summary.

These tests exist because the two failure modes here are both *silent*. A stale
prompt fingerprint makes an A/B comparison look valid when it is comparing two
different prompts; blended token counts make cost-per-paper look plausible while
being wrong. Neither raises, so only a test catches them.
"""

import asyncio

import pytest

from core.graph import provenance


@pytest.fixture(autouse=True)
def _clear_fingerprint_cache():
    provenance._FINGERPRINT_CACHE = None
    yield
    provenance._FINGERPRINT_CACHE = None


# ── Prompt fingerprint ────────────────────────────────────────────────────────

def test_fingerprint_is_real_and_deterministic():
    """`unknown` is the honest failure value, so it must not be the normal one."""
    first = provenance.prompt_fingerprint()
    provenance._FINGERPRINT_CACHE = None
    second = provenance.prompt_fingerprint()

    assert first == second
    assert first != 'unknown', (
        'the fingerprint failed to compute; every run recorded with it is '
        'unattributable, and two different prompts would compare equal'
    )
    assert len(first) == 12
    int(first, 16)          # must be hex


def test_fingerprint_tracks_schema_field_descriptions(monkeypatch):
    """Field descriptions ARE the prompt (schemas.py says so) — editing one must
    change the fingerprint, or a prompt change slips through unversioned."""
    from core.graph import schemas

    baseline = provenance.prompt_fingerprint()
    provenance._FINGERPRINT_CACHE = None

    original = schemas.PaperSynthesis.model_json_schema

    def _edited(*args, **kwargs):
        out = dict(original(*args, **kwargs))
        out['title'] = 'DELIBERATELY DIFFERENT'
        return out

    monkeypatch.setattr(schemas.PaperSynthesis, 'model_json_schema', _edited)
    changed = provenance.prompt_fingerprint()

    assert changed != baseline, 'a schema edit did not move the fingerprint'


def test_fingerprint_ignores_imported_third_party_models():
    """`dir(schemas)` also yields the imported pydantic BaseModel, whose
    model_json_schema() raises — which is what made this return 'unknown'."""
    from core.graph import schemas

    assert 'BaseModel' in dir(schemas), 'precondition: BaseModel is in the namespace'
    assert provenance.prompt_fingerprint() != 'unknown'


# ── Usage accounting ──────────────────────────────────────────────────────────

def test_recorder_separates_failed_calls_from_token_totals():
    recorder = provenance.start_run()
    recorder.record(node='synthesize', tier='smart', ok=True,
                    model='gemini-flash-latest', input_tokens=12000,
                    output_tokens=1400, seconds=8.2)
    recorder.record(node='grade', tier='smart', ok=False, seconds=1.1,
                    error='RateLimitError')

    out = recorder.summary()
    assert out['llm_calls'] == 2
    assert out['llm_calls_failed'] == 1
    assert out['input_tokens'] == 12000
    assert out['by_node']['synthesize']['calls'] == 1
    assert out['by_node']['grade']['calls'] == 1


def test_models_observed_records_the_fallback_not_the_configured_primary():
    """The whole point: `llm_model` in metadata is the configured primary, which
    is wrong whenever the chain falls through. This field must show reality."""
    recorder = provenance.start_run()
    recorder.record(node='read_paper', tier='smart', ok=False, error='RateLimitError')
    recorder.record(node='read_paper', tier='smart', ok=True,
                    model='llama-3.3-70b-versatile', input_tokens=9000, output_tokens=800)

    assert recorder.summary()['models_observed'] == ['llama-3.3-70b-versatile']


async def test_concurrent_runs_do_not_blend_token_counts():
    """The job worker summarizes several papers at once in one process. A module
    global here would bill one paper's tokens to another."""
    async def one_paper(tokens: int) -> dict:
        recorder = provenance.start_run()
        await asyncio.sleep(0)                     # force interleaving
        recorder.record(node='synthesize', tier='smart', ok=True,
                        model='m', input_tokens=tokens, output_tokens=1)
        await asyncio.sleep(0)
        return recorder.summary()

    a, b, c = await asyncio.gather(one_paper(100), one_paper(200), one_paper(300))

    assert (a['input_tokens'], b['input_tokens'], c['input_tokens']) == (100, 200, 300)


def test_collector_extracts_model_and_tokens_from_a_provider_response():
    """Shape check against what LangChain hands back, so a provider that omits
    usage_metadata degrades to None rather than raising inside the callback."""
    class _Msg:
        response_metadata = {'model_name': 'gemini-flash-latest'}
        usage_metadata = {'input_tokens': 4321, 'output_tokens': 99}

    class _Gen:
        message = _Msg()

    class _Result:
        generations = [[_Gen()]]

    recorder = provenance.start_run()
    collector = provenance.make_collector('synthesize', 'smart')
    collector.on_llm_end(_Result())

    call = recorder.calls[0]
    assert call['model'] == 'gemini-flash-latest'
    assert call['input_tokens'] == 4321
    assert call['node'] == 'synthesize'


def test_collector_survives_a_response_it_does_not_understand():
    """Telemetry must never be the thing that fails a completed summary."""
    class _Nonsense:
        generations = []

    recorder = provenance.start_run()
    collector = provenance.make_collector('grade', 'smart')
    collector.on_llm_end(_Nonsense())              # must not raise

    assert recorder.calls[0]['model'] is None
    assert recorder.calls[0]['ok'] is True


def test_recording_outside_a_run_is_a_no_op():
    """Nodes can be called directly (tests, evals) with no recorder started."""
    provenance._current_run.set(None)
    collector = provenance.make_collector('synthesize', 'smart')
    collector.on_llm_end(object())                 # must not raise
