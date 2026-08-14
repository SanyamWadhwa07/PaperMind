"""Cross-paper comparison: what the table is built from.

The comparison is assembled from `summary_data`, whose shape is written by
`core/agent_integration.py`. These tests pin that contract — a rename on either
side silently produced an empty column rather than an error.
"""

import pytest

from core.knowledge.comparison_service import (
    ComparisonError,
    MAX_PAPERS,
    compare_papers,
)


def _paper(pid, *, title='Paper', date='2024-01-01', metrics=None, entities=None,
           findings=None):
    """One `summaries` row in the shape the route selects."""
    return {
        'id': pid,
        'paper_title': title,
        'arxiv_id': f'{pid}.00001',
        'published_date': date,
        'quality_score': 0.8,
        'summary_data': {
            # Written by agent_integration as results.metrics — a list of
            # {metric, value, model, dataset, is_best}.
            'results': {'metrics': metrics or []},
            'entities': entities or {},
            'key_findings': findings or [],
        },
    }


def _rows(*papers):
    return list(papers)


# ── ID count ──────────────────────────────────────────────────────────────────

def test_rejects_fewer_than_two_ids():
    """A single paper is not a comparison. Previously this returned a dict with
    an `error` key, which the route handed back as HTTP 200."""
    with pytest.raises(ComparisonError):
        compare_papers(['a'], None, rows=_rows(_paper('a')))


def test_rejects_more_than_the_cap():
    ids = [str(i) for i in range(MAX_PAPERS + 1)]
    with pytest.raises(ComparisonError):
        compare_papers(ids, None, rows=[])


def test_rejects_when_fewer_than_two_papers_load():
    """Two ids requested, one row returned — there is nothing to compare against."""
    with pytest.raises(ComparisonError):
        compare_papers(['a', 'b'], None, rows=_rows(_paper('a')))


# ── Metrics matrix ────────────────────────────────────────────────────────────

def test_metric_names_are_normalised_across_papers():
    """`top-1` and `accuracy` are the same row of the table."""
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', metrics=[{'metric': 'Top-1', 'value': '76.5'}]),
            _paper('b', metrics=[{'metric': 'accuracy', 'value': '79.1'}]),
        ),
    )
    assert list(result['metrics_matrix']) == ['Accuracy']
    assert result['metrics_matrix']['Accuracy'] == {'a': '76.5', 'b': '79.1'}


def test_missing_metric_becomes_an_explicit_none():
    """The table reads by position, so every row needs a cell per paper."""
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', metrics=[{'metric': 'F1', 'value': '0.91'}]),
            _paper('b', metrics=[{'metric': 'BLEU', 'value': '34.2'}]),
        ),
    )
    assert result['metrics_matrix']['F1'] == {'a': '0.91', 'b': None}
    assert result['metrics_matrix']['BLEU'] == {'a': None, 'b': '34.2'}


def test_repeated_metric_prefers_the_row_marked_best():
    """A paper reports the same measurement per model. The last one written used
    to win by accident; the one the extractor flagged as best should."""
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', metrics=[
                {'metric': 'mAP', 'value': '40.1'},
                {'metric': 'mAP', 'value': '44.8', 'is_best': True},
                {'metric': 'mAP', 'value': '38.0'},
            ]),
            _paper('b', metrics=[{'metric': 'mAP', 'value': '41.0'}]),
        ),
    )
    assert result['metrics_matrix']['mAP']['a'] == '44.8'


def test_blank_and_malformed_metric_rows_are_skipped():
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', metrics=[
                {'metric': 'Accuracy', 'value': ''},   # no value
                {'metric': '', 'value': '9'},          # no name
                'not-a-dict',                          # extractor noise
                {'metric': 'F1', 'value': '0.8'},
            ]),
            _paper('b', metrics=[{'metric': 'F1', 'value': '0.7'}]),
        ),
    )
    assert list(result['metrics_matrix']) == ['F1']


# ── Entity overlap ────────────────────────────────────────────────────────────

def test_tasks_bucket_is_compared():
    """`tasks` is written on every paper but was missing from the hardcoded
    bucket tuple, so task overlap never appeared in the Overlap tab."""
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', entities={'tasks': ['segmentation'], 'models': ['UNet']}),
            _paper('b', entities={'tasks': ['segmentation'], 'models': ['ViT']}),
        ),
    )
    assert result['entity_overlap']['tasks']['segmentation'] == ['a', 'b']


def test_empty_buckets_are_omitted_entirely():
    """`frameworks` was in the old tuple but is never populated, so it shipped
    as an always-empty section."""
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', entities={'models': ['UNet']}),
            _paper('b', entities={'models': ['ViT']}),
        ),
    )
    assert 'frameworks' not in result['entity_overlap']
    assert list(result['entity_overlap']) == ['models']


def test_shared_entity_lists_every_paper_holding_it():
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', entities={'datasets': ['ImageNet', 'COCO']}),
            _paper('b', entities={'datasets': ['ImageNet']}),
        ),
    )
    assert result['entity_overlap']['datasets']['ImageNet'] == ['a', 'b']
    assert result['entity_overlap']['datasets']['COCO'] == ['a']


def test_buckets_come_back_in_display_order():
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', entities={'tasks': ['t'], 'datasets': ['d'], 'models': ['m']}),
            _paper('b', entities={'tasks': ['t']}),
        ),
    )
    assert list(result['entity_overlap']) == ['datasets', 'models', 'tasks']


# ── Papers and ordering ───────────────────────────────────────────────────────

def test_papers_are_ordered_oldest_first():
    result = compare_papers(
        ['a', 'b', 'c'],
        None,
        rows=_rows(
            _paper('a', date='2024-06-01'),
            _paper('b', date='2023-01-01'),
            _paper('c', date='2025-02-01'),
        ),
    )
    assert [p['id'] for p in result['papers']] == ['b', 'a', 'c']
    assert result['temporal_progression'] == ['2023-01-01', '2024-06-01', '2025-02-01']


def test_a_missing_paper_is_reported_not_shown_as_empty():
    """Three ids, two rows: the third must not become a column of dashes
    implying it was compared and had no data."""
    result = compare_papers(
        ['a', 'b', 'gone'],
        None,
        rows=_rows(
            _paper('a', metrics=[{'metric': 'F1', 'value': '1'}]),
            _paper('b'),
        ),
    )
    assert result['missing_ids'] == ['gone']
    assert [p['id'] for p in result['papers']] == ['a', 'b']
    assert 'gone' not in result['metrics_matrix']['F1']


def test_findings_from_different_papers_cluster_together():
    shared = 'The proposed attention module improves accuracy on small objects'
    result = compare_papers(
        ['a', 'b'],
        None,
        rows=_rows(
            _paper('a', findings=[shared]),
            _paper('b', findings=[shared + ' by a wide margin']),
        ),
    )
    multi = [c for c in result['findings_clusters'] if len(c['papers']) > 1]
    assert multi, 'near-identical findings should land in one cluster'
    assert multi[0]['unique_to'] is None


def test_does_not_query_when_rows_are_supplied():
    """The route already read these rows for the ownership check; reading them
    again pulled the full summary_data JSONB for up to ten papers twice."""
    class Exploding:
        def table(self, *_a, **_k):
            raise AssertionError('compare_papers must not query when given rows')

    compare_papers(['a', 'b'], Exploding(), rows=_rows(_paper('a'), _paper('b')))
