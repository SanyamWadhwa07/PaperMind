"""Extracting prose from an LLM response, whichever shape the provider used.

The list-of-blocks case is not hypothetical: it is what produced a stored peer
review of `{"type": ..., "text": ..., "extras": ...}`, with the real review
trapped as a JSON string inside `text`, and a review card whose every field
rendered undefined.
"""

from types import SimpleNamespace

import pytest

from core.llm.json_parse import parse_json_object
from core.llm.response import message_text


def msg(content):
    return SimpleNamespace(content=content)


def test_plain_string_content():
    assert message_text(msg('hello')) == 'hello'


def test_list_of_text_blocks_is_joined():
    assert message_text(msg([
        {'type': 'text', 'text': 'Deep image '},
        {'type': 'text', 'text': 'enhancement.'},
    ])) == 'Deep image enhancement.'


def test_block_without_a_type_is_still_text():
    assert message_text(msg([{'text': 'hi'}])) == 'hi'


def test_non_text_blocks_are_skipped():
    """Concatenating a tool call into the prose would corrupt the answer."""
    assert message_text(msg([
        {'type': 'text', 'text': 'answer'},
        {'type': 'tool_use', 'id': 'x', 'input': {}},
        {'type': 'thinking', 'thinking': 'ignore me'},
    ])) == 'answer'


def test_object_blocks_with_a_text_attribute():
    assert message_text(msg([SimpleNamespace(text='from an object')])) == 'from an object'


def test_bare_strings_in_the_list():
    assert message_text(msg(['a', 'b'])) == 'ab'


@pytest.mark.parametrize('content', [None, ''])
def test_empty_content_is_the_empty_string(content):
    assert message_text(msg(content)) == ''


def test_a_raw_string_response_works_without_a_content_attribute():
    assert message_text('just text') == 'just text'


def test_json_survives_the_round_trip_through_blocks():
    """The end-to-end failure: a JSON answer delivered as a content block.

    Previously the list was stringified, and the JSON parser then read the
    *envelope* — returning {'type', 'text', 'extras'} instead of the review.
    """
    review = '{"novelty": 7, "recommendation": "accept"}'
    response = msg([{'type': 'text', 'text': review, 'extras': {}}])

    parsed = parse_json_object(message_text(response))

    assert parsed == {'novelty': 7, 'recommendation': 'accept'}
    assert 'extras' not in parsed
