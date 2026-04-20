"""Unit tests for entity relationship inference in EntityAgent."""
import sys
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def mock_heavy_deps():
    """Prevent importing nltk/spacy/torch at test collection time."""
    sys.modules.setdefault('nltk', MagicMock())
    sys.modules.setdefault('fitz', MagicMock())
    # Mock backend.main so EntityAgent can be imported without full backend deps
    mock_main = MagicMock()
    mock_main.EnhancedEntityExtractor = MagicMock
    sys.modules['backend.main'] = mock_main
    yield


@pytest.fixture
def entity_agent():
    from core.agents.entity_agent import EntityAgent
    agent = EntityAgent.__new__(EntityAgent)
    agent.name = "EntityAgent"
    agent.experience = None
    agent.message_bus = None
    agent.entity_extractor = MagicMock()
    agent.extracted_entities = {}
    agent.uncertain_entities = set()
    return agent


def test_infer_uses_relationship(entity_agent):
    sections = {
        'methodology': 'We train the Transformer on WMT 2014 English-German dataset.',
    }
    entities = {
        'models': ['Transformer'],
        'datasets': ['WMT 2014'],
        'metrics': [],
        'tasks': [],
    }
    rels = entity_agent._infer_relationships(sections, entities)
    uses_rels = [r for r in rels if r['relationship_type'] == 'uses']
    assert len(uses_rels) >= 1
    assert uses_rels[0]['entity_1'] == 'Transformer'
    assert uses_rels[0]['entity_2'] == 'WMT 2014'


def test_infer_evaluated_on_relationship(entity_agent):
    sections = {
        'results': 'BLEU is measured on WMT 2014 test set.',
    }
    entities = {
        'models': [],
        'datasets': ['WMT 2014'],
        'metrics': ['BLEU'],
        'tasks': [],
    }
    rels = entity_agent._infer_relationships(sections, entities)
    eval_rels = [r for r in rels if r['relationship_type'] == 'evaluated-on']
    assert len(eval_rels) >= 1
    assert eval_rels[0]['entity_1'] == 'BLEU'
    assert eval_rels[0]['entity_2'] == 'WMT 2014'


def test_infer_compared_to_requires_signal_word(entity_agent):
    sections = {
        'results': 'BERT and GPT-2 are both language models.',
    }
    entities = {
        'models': ['BERT', 'GPT-2'],
        'datasets': [],
        'metrics': [],
        'tasks': [],
    }
    rels = entity_agent._infer_relationships(sections, entities)
    compared_rels = [r for r in rels if r['relationship_type'] == 'compared-to']
    # No comparison signal words → no compared-to relationship
    assert len(compared_rels) == 0


def test_infer_compared_to_with_signal_word(entity_agent):
    sections = {
        'results': 'Our model outperforms BERT vs GPT-2 on the benchmark.',
    }
    entities = {
        'models': ['BERT', 'GPT-2'],
        'datasets': [],
        'metrics': [],
        'tasks': [],
    }
    rels = entity_agent._infer_relationships(sections, entities)
    compared_rels = [r for r in rels if r['relationship_type'] == 'compared-to']
    assert len(compared_rels) >= 1


def test_infer_applied_to_relationship(entity_agent):
    sections = {
        'methodology': 'Transformer is applied to image classification tasks.',
    }
    entities = {
        'models': ['Transformer'],
        'datasets': [],
        'metrics': [],
        'tasks': ['image classification'],
    }
    rels = entity_agent._infer_relationships(sections, entities)
    applied_rels = [r for r in rels if r['relationship_type'] == 'applied-to']
    assert len(applied_rels) >= 1


def test_infer_deduplicates_relationships(entity_agent):
    sections = {
        'abstract': 'Transformer on WMT 2014.',
        'methodology': 'We train Transformer on WMT 2014 dataset.',
    }
    entities = {
        'models': ['Transformer'],
        'datasets': ['WMT 2014'],
        'metrics': [],
        'tasks': [],
    }
    rels = entity_agent._infer_relationships(sections, entities)
    uses_rels = [r for r in rels if r['relationship_type'] == 'uses']
    assert len(uses_rels) == 1  # deduplicated


def test_infer_returns_confidence(entity_agent):
    sections = {'methodology': 'GPT-2 uses BookCorpus for training.'}
    entities = {
        'models': ['GPT-2'],
        'datasets': ['BookCorpus'],
        'metrics': [],
        'tasks': [],
    }
    rels = entity_agent._infer_relationships(sections, entities)
    for rel in rels:
        assert 0.0 < rel['confidence'] <= 1.0
