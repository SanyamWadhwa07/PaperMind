"""Tests for EntityAgent — model/dataset/metric extraction from known text."""

import asyncio
import pytest


@pytest.fixture
def entity_agent():
    from core.agents.entity_agent import EntityAgent
    return EntityAgent()


@pytest.fixture
def nlp_sections():
    return {
        'abstract': (
            'We fine-tune BERT on the GLUE benchmark and evaluate using accuracy and F1 score. '
            'Our approach uses the PyTorch framework.'
        ),
        'methodology': (
            'We use BERT-Large and RoBERTa as backbone models. '
            'The models are trained on SQuAD 2.0 and CoNLL-2003 datasets. '
            'Evaluation is performed with F1 score and exact match metrics.'
        ),
        'results': (
            'BERT achieves 90.9 F1 on SQuAD 2.0, outperforming LSTM by 8 points. '
            'RoBERTa improves further to 92.1 F1.'
        ),
    }


@pytest.fixture
def cv_sections():
    return {
        'abstract': (
            'We train ResNet-50 and ViT-B/16 on ImageNet and CIFAR-10. '
            'Evaluation uses top-1 accuracy and mAP.'
        ),
        'results': (
            'ResNet-50 achieves 76.1% top-1 accuracy on ImageNet. '
            'ViT-B/16 reaches 81.8% using PyTorch with CUDA acceleration.'
        ),
    }


@pytest.mark.asyncio
async def test_extracts_known_nlp_models(entity_agent, nlp_sections):
    """EntityAgent should detect BERT and RoBERTa from NLP paper sections."""
    result = await entity_agent.process({
        'sections': nlp_sections,
        'domain': 'nlp',
    })
    entities = result.get('entities', {})
    models = [m.upper() for m in entities.get('models', [])]
    assert any('BERT' in m for m in models), f'BERT not found in {models}'


@pytest.mark.asyncio
async def test_extracts_known_nlp_datasets(entity_agent, nlp_sections):
    """EntityAgent should detect SQuAD and CoNLL from NLP sections."""
    result = await entity_agent.process({
        'sections': nlp_sections,
        'domain': 'nlp',
    })
    datasets = [d.upper() for d in result.get('entities', {}).get('datasets', [])]
    assert any('SQUAD' in d or 'CONLL' in d for d in datasets), (
        f'SQuAD/CoNLL not found in {datasets}'
    )


@pytest.mark.asyncio
async def test_extracts_metrics(entity_agent, nlp_sections):
    """EntityAgent should detect F1/accuracy as metrics."""
    result = await entity_agent.process({
        'sections': nlp_sections,
        'domain': 'nlp',
    })
    metrics = [m.lower() for m in result.get('entities', {}).get('metrics', [])]
    assert any('f1' in m or 'accuracy' in m for m in metrics), (
        f'f1/accuracy not found in {metrics}'
    )


@pytest.mark.asyncio
async def test_result_has_expected_keys(entity_agent, cv_sections):
    """Result must always include models, datasets, metrics, tasks keys."""
    result = await entity_agent.process({'sections': cv_sections, 'domain': 'cv'})
    entities = result.get('entities', {})
    for key in ('models', 'datasets', 'metrics', 'tasks'):
        assert key in entities, f'Missing key: {key}'
        assert isinstance(entities[key], list), f'{key} should be a list'


@pytest.mark.asyncio
async def test_empty_sections_returns_empty_entities(entity_agent):
    """Empty input should not raise and should return empty entity lists."""
    result = await entity_agent.process({'sections': {}, 'domain': 'general'})
    entities = result.get('entities', {})
    for key in ('models', 'datasets', 'metrics'):
        assert isinstance(entities.get(key, []), list)
