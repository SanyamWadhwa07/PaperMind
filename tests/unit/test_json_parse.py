"""Recovering JSON from the shapes LLMs actually emit.

Every case here was seen in production logs as
`Expecting property name enclosed in double quotes: line 1 column 2 (char 1)`,
which the agents caught, logged at warning level, and swallowed — so the feature
returned nothing while the request still looked successful.
"""

import pytest

from core.llm.json_parse import extract_json_span, parse_json_object


def test_plain_object():
    assert parse_json_object('{"a": 1}') == {'a': 1}


def test_object_wrapped_in_prose():
    raw = 'Here is the analysis you asked for:\n{"gaps": ["x"]}\nHope that helps!'
    assert parse_json_object(raw) == {'gaps': ['x']}


def test_markdown_fence():
    raw = '```json\n{"slides": [{"title": "T"}]}\n```'
    assert parse_json_object(raw)['slides'][0]['title'] == 'T'


def test_reasoning_preamble_is_ignored():
    """A `{` inside <think> used to anchor the greedy match, swallowing the answer."""
    raw = '<think>I should return {something} useful</think>\n{"score": 7}'
    assert parse_json_object(raw) == {'score': 7}


def test_single_quoted_python_dialect():
    """The exact failure: char 1 is `'`, not `"`."""
    assert parse_json_object("{'component': 'attention', 'delta': -1.2}") == {
        'component': 'attention',
        'delta': -1.2,
    }


def test_unquoted_keys():
    assert parse_json_object('{component: "attention", delta: 2}') == {
        'component': 'attention',
        'delta': 2,
    }


def test_trailing_comma():
    assert parse_json_object('{"a": 1, "b": [2, 3,],}') == {'a': 1, 'b': [2, 3]}


def test_python_literals():
    assert parse_json_object("{'ok': True, 'note': None}") == {'ok': True, 'note': None}


def test_nested_braces_are_balanced_not_greedy():
    raw = '{"outer": {"inner": 1}} trailing text with a stray }'
    assert parse_json_object(raw) == {'outer': {'inner': 1}}


def test_brace_inside_string_does_not_end_the_span():
    raw = '{"caption": "Figure 1: the set {a, b}", "page": 3}'
    assert parse_json_object(raw)['page'] == 3


def test_escaped_quote_inside_string():
    raw = r'{"quote": "he said \"no\"", "n": 1}'
    assert parse_json_object(raw)['n'] == 1


@pytest.mark.parametrize('raw', ['', None, 'no json here at all', '[1, 2, 3]', '{'])
def test_unparseable_returns_empty_dict_rather_than_raising(raw):
    """Callers rely on `{}` to mean "no data"; an exception would break the pipeline."""
    assert parse_json_object(raw) == {}


def test_balanced_but_unparseable_span_does_not_shadow_the_real_object():
    """`{\\alpha}` is balanced, so stopping at the first span would lose the answer."""
    raw = 'latex {\\alpha} then {"real": true}'
    assert extract_json_span(raw) == '{\\alpha}'
    assert parse_json_object(raw) == {'real': True}


# ── Truncation at the token ceiling ──────────────────────────────────────────
# A model that runs out of tokens stops mid-array or mid-string. The object
# never closes, so no balanced span exists and the whole reply used to be
# discarded — which is how a peer review with four scores and three written
# concerns surfaced as "model returned no parseable JSON object".

def test_truncated_mid_string_keeps_what_arrived():
    raw = '{"novelty": 7, "soundness": 6, "major_concerns": ["No baseline compa'
    parsed = parse_json_object(raw)
    assert parsed['novelty'] == 7
    assert parsed['soundness'] == 6


def test_truncated_mid_array_keeps_complete_elements():
    raw = '{"recommendation": "reject", "concerns": ["first one", "second one", "thir'
    parsed = parse_json_object(raw)
    assert parsed['recommendation'] == 'reject'
    assert 'first one' in parsed['concerns']


def test_truncated_after_a_complete_field():
    raw = '{"a": 1, "b": 2,'
    assert parse_json_object(raw) == {'a': 1, 'b': 2}


def test_truncated_inside_a_fenced_block():
    raw = '```json\n{"novelty": 3, "notes": ["one", "tw'
    assert parse_json_object(raw)['novelty'] == 3


def test_complete_json_is_never_routed_through_salvage():
    """Salvage must not truncate a reply that was already whole."""
    raw = '{"a": 1, "b": [1, 2, 3], "c": {"d": 4}}'
    assert parse_json_object(raw) == {'a': 1, 'b': [1, 2, 3], 'c': {'d': 4}}


def test_truncation_with_nothing_complete_yet_returns_empty():
    assert parse_json_object('{"novel') == {}
