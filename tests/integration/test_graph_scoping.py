"""What the knowledge graph is allowed to contain.

The graph used to source its entity nodes from `entity_relationships` — the
cross-paper experience store, which has no `user_id` and no `summary_id`. Every
graph therefore rendered up to 300 relationships belonging to whoever had
processed papers most recently, attached to nothing else on screen. These tests
pin both halves of the fix: entities come from the viewer's own papers, and an
anchored graph is actually anchored.
"""

from types import SimpleNamespace

import pytest

from core.knowledge.graph_service import get_knowledge_graph


class FakeQuery:
    """Records what was asked for and replays canned rows."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def in_(self, column, values):
        self._rows = [r for r in self._rows if r.get(column) in values]
        return self

    def gte(self, column, value):
        self._rows = [r for r in self._rows if (r.get(column) or 0) >= value]
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return SimpleNamespace(data=list(self._rows))


class FakeSupabase:
    def __init__(self, tables):
        self._tables = tables
        self.tables_queried = []

    def table(self, name):
        self.tables_queried.append(name)
        return FakeQuery([dict(r) for r in self._tables.get(name, [])])


def paper(pid, title, *, user='user-1', models=(), datasets=()):
    """A summaries row shaped the way the graph query selects it."""
    return {
        'id': pid,
        'user_id': user,
        'paper_title': title,
        'arxiv_id': f'{pid}.0001',
        'primary_category': 'nlp',
        'published_date': '2024-01-01',
        'quality_score': 0.8,
        # `summary_data->entities` arrives under the leaf key.
        'entities': {'models': list(models), 'datasets': list(datasets)},
    }


@pytest.fixture
def library():
    return {
        'summaries': [
            paper('anchor', 'The Anchor', models=['BERT'], datasets=['SQuAD']),
            paper('near', 'A Neighbour', models=['BERT'], datasets=['GLUE']),
            paper('far', 'Unrelated Work', models=['ResNet']),
            paper('other-user', 'Someone Else', user='user-2', models=['BERT']),
        ],
        'paper_similarity': [
            {'paper_a_id': 'anchor', 'paper_b_id': 'near', 'similarity_score': 0.81},
        ],
        # Populated, and must stay unread: it is global across accounts.
        'entity_relationships': [
            {
                'entity_1': 'LeakedModel', 'entity_1_type': 'model',
                'entity_2': 'LeakedData', 'entity_2_type': 'dataset',
                'relationship_type': 'co-occurs', 'frequency_count': 3,
                'confidence_score': 0.9,
            }
        ],
    }


def labels(graph, group):
    return {n['label'] for n in graph['nodes'] if n['group'] == group}


def test_entity_relationships_is_never_read(library):
    """It holds every account's entities, so it cannot source a user's graph."""
    client = FakeSupabase(library)

    get_knowledge_graph('user-1', client, anchor_summary_id='anchor')

    assert 'entity_relationships' not in client.tables_queried


def test_another_users_entities_do_not_appear(library):
    graph = get_knowledge_graph('user-1', FakeSupabase(library), anchor_summary_id='anchor')

    everything = {n['label'] for n in graph['nodes']}
    assert 'LeakedModel' not in everything
    assert 'Someone Else' not in everything


def test_anchor_graph_is_the_anchors_neighbourhood(library):
    graph = get_knowledge_graph('user-1', FakeSupabase(library), anchor_summary_id='anchor')

    assert labels(graph, 'paper') == {'The Anchor', 'A Neighbour'}
    anchors = [n for n in graph['nodes'] if n.get('is_anchor')]
    assert len(anchors) == 1 and anchors[0]['label'] == 'The Anchor'


def test_library_graph_without_an_anchor_holds_every_paper(library):
    graph = get_knowledge_graph('user-1', FakeSupabase(library))

    assert labels(graph, 'paper') == {'The Anchor', 'A Neighbour', 'Unrelated Work'}
    assert not any(n.get('is_anchor') for n in graph['nodes'])


def test_entities_come_from_the_papers_own_extraction(library):
    graph = get_knowledge_graph('user-1', FakeSupabase(library), anchor_summary_id='anchor')

    # The anchor's own entities are always shown.
    assert {'BERT', 'SQuAD'} <= labels(graph, 'entity')


def test_a_shared_entity_records_how_many_papers_mention_it(library):
    graph = get_knowledge_graph('user-1', FakeSupabase(library), anchor_summary_id='anchor')

    bert = next(n for n in graph['nodes'] if n['label'] == 'BERT')
    # The anchor and its neighbour — not the other user's paper.
    assert bert['paper_count'] == 2


def test_an_unshared_entity_of_a_neighbour_is_dropped(library):
    """A leaf hanging off one non-anchor paper adds a node and no information."""
    graph = get_knowledge_graph('user-1', FakeSupabase(library), anchor_summary_id='anchor')

    assert 'GLUE' not in labels(graph, 'entity')


def test_papers_are_linked_to_what_they_mention(library):
    graph = get_knowledge_graph('user-1', FakeSupabase(library), anchor_summary_id='anchor')

    mentions = [e for e in graph['edges'] if e['group'] == 'mentions']
    assert any(e['from'] == 'paper_anchor' and e['to'].endswith('bert') for e in mentions)


def test_similarity_edges_survive(library):
    graph = get_knowledge_graph('user-1', FakeSupabase(library), anchor_summary_id='anchor')

    sim = [e for e in graph['edges'] if e['group'] == 'similarity']
    assert len(sim) == 1
    assert sim[0]['title'] == '81% similar'


def test_entities_stored_as_json_text_are_still_read():
    """PostgREST hands back a JSON leaf as text depending on the column type."""
    row = paper('anchor', 'The Anchor', models=['BERT'])
    row['entities'] = '{"models": ["BERT"], "datasets": []}'

    graph = get_knowledge_graph(
        'user-1', FakeSupabase({'summaries': [row]}), anchor_summary_id='anchor'
    )

    assert 'BERT' in labels(graph, 'entity')


def test_a_paper_with_no_entities_still_renders():
    row = paper('anchor', 'The Anchor')
    row['entities'] = None

    graph = get_knowledge_graph(
        'user-1', FakeSupabase({'summaries': [row]}), anchor_summary_id='anchor'
    )

    assert labels(graph, 'paper') == {'The Anchor'}
    assert labels(graph, 'entity') == set()
