"""Shared pytest fixtures."""
import sys
from pathlib import Path

# Ensure project root is on the path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'core'))

import pytest


@pytest.fixture
def sample_pdf_text():
    return (
        "Attention Is All You Need\n"
        "We propose the Transformer, a model architecture eschewing recurrence.\n"
        "We train on WMT 2014 English-to-German dataset.\n"
        "The model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task.\n"
        "Compared to LSTM and ConvS2S, the Transformer outperforms both baselines.\n"
        "Future work includes applying this architecture to image and audio tasks.\n"
    )


@pytest.fixture
def sample_sections(sample_pdf_text):
    return {
        'abstract': 'We propose the Transformer architecture for sequence transduction.',
        'introduction': 'Recurrent neural networks have been the dominant approach.',
        'methodology': (
            'We train the Transformer on WMT 2014 English-to-German dataset using BLEU metric. '
            'The model uses multi-head attention instead of LSTM.'
        ),
        'results': (
            'The Transformer achieves 28.4 BLEU on WMT 2014 English-German. '
            'Compared to LSTM vs ConvS2S, our model outperforms both baselines.'
        ),
        'conclusion': 'The Transformer is effective for neural machine translation tasks.',
    }


@pytest.fixture
def mock_supabase():
    """Minimal Supabase client mock."""
    from unittest.mock import MagicMock
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    client.rpc.return_value.execute.return_value.data = []
    return client
