"""Shared pytest fixtures."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'core'))

import pytest


@pytest.fixture(scope='session')
def test_pdf_path(tmp_path_factory):
    """Create a minimal 3-page academic paper PDF using PyMuPDF."""
    fitz = pytest.importorskip('fitz', reason='PyMuPDF (fitz) required')
    tmp_dir = tmp_path_factory.mktemp('pdfs')
    pdf_path = tmp_dir / 'test_paper.pdf'

    doc = fitz.open()

    p0 = doc.new_page()
    p0.insert_text((72, 72), (
        'Attention Is All You Need\n\n'
        'Vaswani et al.\n\n'
        'Abstract\n\n'
        'We propose the Transformer, a model architecture eschewing recurrence entirely '
        'and instead relying on an attention mechanism to draw global dependencies between input and output.'
    ), fontsize=11)

    p1 = doc.new_page()
    p1.insert_text((72, 72), (
        'Introduction\n\n'
        'Recurrent neural networks, long short-term memory (LSTM) and gated recurrent neural networks '
        'have been firmly established as state-of-the-art approaches in sequence modelling.\n\n'
        'Methodology\n\n'
        'We train the Transformer on the WMT 2014 English-to-German dataset using the BLEU metric. '
        'Our model uses multi-head self-attention with scaled dot-product attention.'
    ), fontsize=11)

    p2 = doc.new_page()
    p2.insert_text((72, 72), (
        'Results\n\n'
        'The Transformer achieves 28.4 BLEU on the WMT 2014 English-to-German translation task, '
        'outperforming LSTM and ConvS2S by 2 BLEU points.\n\n'
        'Conclusion\n\n'
        'The Transformer is the first sequence transduction model based entirely on attention, '
        'replacing the recurrent layers most commonly used in encoder-decoder architectures.'
    ), fontsize=11)

    doc.save(str(pdf_path))
    doc.close()
    return str(pdf_path)


@pytest.fixture
def sample_pdf_text():
    return (
        'Attention Is All You Need\n'
        'We propose the Transformer, a model architecture eschewing recurrence.\n'
        'We train on WMT 2014 English-to-German dataset.\n'
        'The model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task.\n'
        'Compared to LSTM and ConvS2S, the Transformer outperforms both baselines.\n'
        'Future work includes applying this architecture to image and audio tasks.\n'
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
