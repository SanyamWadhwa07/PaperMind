"""
Paper processing routes - integrates main.py summarization with database
"""
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.utils import token_required
from datetime import datetime
from pathlib import Path
import sys
import time
import tempfile

# Add parent directory to path to import core modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.agent_integration import run_agent_mode
from backend.main import load_config, load_patterns

process_bp = Blueprint('process', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

ALLOWED_EXTENSIONS = {'pdf'}
MAX_PDF_PAGES = 200


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_pdf_bytes(file_stream) -> bool:
    """Check magic bytes to ensure file is actually a PDF."""
    header = file_stream.read(8)
    file_stream.seek(0)
    return header.startswith(b'%PDF-')


def validate_pdf_page_count(path: str) -> bool:
    """Reject PDFs with more than MAX_PDF_PAGES pages."""
    try:
        import fitz
        doc = fitz.open(path)
        count = doc.page_count
        doc.close()
        return count <= MAX_PDF_PAGES
    except Exception:
        return True  # allow if we can't check

@process_bp.route('/process/upload', methods=['POST'])
@token_required
def upload_and_process():
    """Upload PDF and process it through the summarizer"""
    try:
        # Check if file is in request
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Only PDF files are allowed'}), 400

        if not validate_pdf_bytes(file):
            return jsonify({'error': 'File does not appear to be a valid PDF'}), 400

        # Save file to temporary location
        filename = secure_filename(file.filename)
        temp_dir = Path(tempfile.gettempdir())
        temp_path = temp_dir / filename
        file.save(str(temp_path))

        if not validate_pdf_page_count(str(temp_path)):
            temp_path.unlink(missing_ok=True)
            return jsonify({'error': f'PDF exceeds {MAX_PDF_PAGES} page limit'}), 400
        
        try:
            # Load config and patterns
            config = load_config(None)
            patterns = load_patterns('patterns.json')
            
            # Process the paper using agent mode
            start_time = time.time()
            summary_result = run_agent_mode(str(temp_path), config, patterns)
            processing_time = time.time() - start_time
            
            # Prepare summary data for database with 4 summary types
            summary_data = {
                'user_id': request.user_id,
                'paper_title': summary_result.get('title', filename),
                'paper_authors': summary_result.get('authors', []),
                'paper_url': summary_result.get('paper_url'),
                'arxiv_id': summary_result.get('arxiv_id'),
                'summary_data': {
                    'summaries': summary_result.get('summaries', {}),  # 4 distinct summaries
                    'key_findings': summary_result.get('key_findings', []),
                    'methodology': summary_result.get('methodology', {}),
                    'results': summary_result.get('results', {}),
                    'datasets': summary_result.get('datasets', []),
                    'models': summary_result.get('models', []),
                    'metrics': summary_result.get('metrics', []),
                    'tasks': summary_result.get('tasks', []),
                    'entities': {  # Nested for EntityDisplay component
                        'datasets': summary_result.get('datasets', []),
                        'models': summary_result.get('models', []),
                        'metrics': summary_result.get('metrics', []),
                        'tasks': summary_result.get('tasks', [])
                    },
                    'figures': summary_result.get('figures', []),
                    'sections_found': summary_result.get('sections_found', []),
                    'section_count': summary_result.get('section_count', 0),
                    'limitations': summary_result.get('limitations', []),
                    'future_work': summary_result.get('future_work', []),
                    'agent_metadata': summary_result.get('agent_metadata', {})
                },
                'model_used': summary_result.get('agent_metadata', {}).get('llm_backend', 'ollama-qwen2.5:3b'),
                'processing_time_seconds': round(processing_time, 2),
                'word_count': sum(len(s.split()) for s in summary_result.get('summaries', {}).values()),
                'created_at': datetime.utcnow().isoformat()
            }
            
            # Add quality score + section summaries to stored data
            quality_score = summary_result.get('agent_metadata', {}).get('summary_quality')
            summary_data['summary_data']['section_summaries'] = summary_result.get('section_summaries', {})
            summary_data['quality_score'] = quality_score

            # Add abstract text for embedding
            abstract_text = summary_result.get('sections', {}).get('abstract', '')
            summary_data['abstract_text'] = abstract_text[:2000]

            # Duplicate detection via pgvector
            try:
                from core.knowledge.embedding_service import embed_paper
                embedding = embed_paper(
                    title=summary_data['paper_title'],
                    abstract=abstract_text,
                    keywords=summary_result.get('models', []) + summary_result.get('datasets', [])
                )
                dup_result = supabase.rpc('find_duplicate_papers', {
                    'p_embedding': embedding.tolist(),
                    'p_user_id': request.user_id,
                    'p_threshold': 0.95
                }).execute()
                if dup_result.data:
                    return jsonify({
                        'duplicate': True,
                        'existing_id': dup_result.data[0]['id'],
                        'message': 'This paper already exists in your library'
                    }), 409
                summary_data['embedding'] = embedding.tolist()
            except Exception:
                pass  # degrade gracefully — embedding not critical

            # Save to database
            result = supabase.table('summaries').insert(summary_data).execute()

            if not result.data:
                return jsonify({'error': 'Failed to save summary'}), 500

            new_id = result.data[0]['id']

            # Post-save: compute similarity cache + citation lineage (best-effort)
            try:
                from core.knowledge.graph_service import compute_and_cache_similarity
                compute_and_cache_similarity(new_id, request.user_id, supabase)
            except Exception:
                pass

            try:
                from core.knowledge.citation_extractor import (
                    extract_citations, extract_citation_contexts,
                    match_arxiv_ids_to_library
                )
                from core.knowledge.lineage_service import (
                    infer_lineage_from_citations, infer_lineage_from_similarity
                )
                ref_text = summary_result.get('sections', {}).get('__references__', '')
                if ref_text:
                    full_text = ' '.join(summary_result.get('sections', {}).values())
                    citations = extract_citations(ref_text)
                    citations = extract_citation_contexts(full_text, citations)
                    citations = match_arxiv_ids_to_library(citations, supabase, request.user_id)
                    # Save citations to DB
                    citation_rows = [
                        {
                            'source_summary_id': new_id,
                            'cited_arxiv_id': c.get('cited_arxiv_id'),
                            'cited_title': c.get('cited_title'),
                            'year': c.get('year'),
                            'confidence': c.get('confidence', 0.7),
                        }
                        for c in citations[:100]
                    ]
                    if citation_rows:
                        supabase.table('paper_citations').insert(citation_rows).execute()
                    infer_lineage_from_citations(new_id, citations, supabase)
                    infer_lineage_from_similarity(new_id, supabase)
            except Exception:
                pass

            # Log activity
            supabase.table('user_activity').insert({
                'user_id': request.user_id,
                'activity_type': 'summarize',
                'activity_data': {
                    'summary_id': new_id,
                    'paper_title': summary_data['paper_title'],
                    'processing_time': processing_time
                },
                'created_at': datetime.utcnow().isoformat()
            }).execute()

            return jsonify({
                'message': 'Paper processed successfully',
                'summary_id': new_id,
                'summary': result.data[0],
                'processing_time': processing_time
            }), 201

        finally:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Failed to process paper: {str(e)}'}), 500

@process_bp.route('/process/arxiv', methods=['POST'])
@token_required
def process_from_arxiv():
    """Process paper directly from arXiv ID or URL"""
    try:
        data = request.get_json()
        arxiv_input = data.get('arxiv_id', '').strip()
        
        if not arxiv_input:
            return jsonify({'error': 'arXiv ID or URL required'}), 400
        
        # Extract arxiv ID from URL if needed
        import re
        match = re.search(r'(\d{4}\.\d{4,5}(v\d+)?)', arxiv_input)
        if match:
            arxiv_id = match.group(1)
        else:
            return jsonify({'error': 'Invalid arXiv ID format'}), 400
        
        # Fetch paper from arXiv
        import arxiv
        search = arxiv.Search(id_list=[arxiv_id])
        paper = next(search.results(), None)
        
        if not paper:
            return jsonify({'error': 'Paper not found on arXiv'}), 404
        
        # Download PDF
        import requests
        temp_dir = Path(tempfile.gettempdir())
        temp_path = temp_dir / f"{arxiv_id}.pdf"
        
        response = requests.get(paper.pdf_url, timeout=60)
        response.raise_for_status()
        temp_path.write_bytes(response.content)
        
        try:
            # Load config and patterns
            config = load_config(None)
            patterns = load_patterns('patterns.json')
            
            # Process the paper using agent mode
            start_time = time.time()
            summary_result = run_agent_mode(str(temp_path), config, patterns)
            processing_time = time.time() - start_time
            
            # Prepare summary data with 4 summary types
            summary_data = {
                'user_id': request.user_id,
                'paper_title': paper.title,
                'paper_authors': [author.name for author in paper.authors],
                'paper_url': paper.pdf_url,
                'arxiv_id': arxiv_id,
                'summary_data': {
                    'summaries': summary_result.get('summaries', {}),  # 4 distinct summaries
                    'key_findings': summary_result.get('key_findings', []),
                    'methodology': summary_result.get('methodology', {}),
                    'results': summary_result.get('results', {}),
                    'datasets': summary_result.get('datasets', []),
                    'models': summary_result.get('models', []),
                    'metrics': summary_result.get('metrics', []),
                    'tasks': summary_result.get('tasks', []),
                    'entities': {  # Nested for EntityDisplay component
                        'datasets': summary_result.get('datasets', []),
                        'models': summary_result.get('models', []),
                        'metrics': summary_result.get('metrics', []),
                        'tasks': summary_result.get('tasks', [])
                    },
                    'figures': summary_result.get('figures', []),
                    'sections_found': summary_result.get('sections_found', []),
                    'section_count': summary_result.get('section_count', 0),
                    'limitations': summary_result.get('limitations', []),
                    'future_work': summary_result.get('future_work', []),
                    'abstract_original': paper.summary,
                    'agent_metadata': summary_result.get('agent_metadata', {})
                },
                'model_used': summary_result.get('agent_metadata', {}).get('llm_backend', 'ollama-qwen2.5:3b'),
                'processing_time_seconds': round(processing_time, 2),
                'word_count': sum(len(s.split()) for s in summary_result.get('summaries', {}).values()),
                'created_at': datetime.utcnow().isoformat(),
                # Store arXiv publication date
                'published_date': paper.published.strftime('%Y-%m-%d') if getattr(paper, 'published', None) else None,
                'primary_category': data.get('primary_category', getattr(paper, 'primary_category', None)),
                'abstract_text': paper.summary[:2000] if paper.summary else None,
            }

            # Add quality score + section summaries
            quality_score = summary_result.get('agent_metadata', {}).get('summary_quality')
            summary_data['summary_data']['section_summaries'] = summary_result.get('section_summaries', {})
            summary_data['quality_score'] = quality_score

            # Duplicate detection + embedding
            try:
                from core.knowledge.embedding_service import embed_paper
                embedding = embed_paper(
                    title=paper.title,
                    abstract=paper.summary or '',
                    keywords=summary_result.get('models', []) + summary_result.get('datasets', [])
                )
                dup_result = supabase.rpc('find_duplicate_papers', {
                    'p_embedding': embedding.tolist(),
                    'p_user_id': request.user_id,
                    'p_threshold': 0.95
                }).execute()
                if dup_result.data:
                    return jsonify({
                        'duplicate': True,
                        'existing_id': dup_result.data[0]['id'],
                        'message': 'This paper already exists in your library'
                    }), 409
                summary_data['embedding'] = embedding.tolist()
            except Exception:
                pass

            # Save to database
            result = supabase.table('summaries').insert(summary_data).execute()

            if not result.data:
                return jsonify({'error': 'Failed to save summary'}), 500

            new_id = result.data[0]['id']

            # Post-save: similarity cache + citation lineage
            try:
                from core.knowledge.graph_service import compute_and_cache_similarity
                compute_and_cache_similarity(new_id, request.user_id, supabase)
            except Exception:
                pass

            try:
                from core.knowledge.citation_extractor import (
                    extract_citations, extract_citation_contexts, match_arxiv_ids_to_library
                )
                from core.knowledge.lineage_service import (
                    infer_lineage_from_citations, infer_lineage_from_similarity
                )
                ref_text = summary_result.get('sections', {}).get('__references__', '')
                if ref_text:
                    full_text = ' '.join(summary_result.get('sections', {}).values())
                    citations = extract_citations(ref_text)
                    citations = extract_citation_contexts(full_text, citations)
                    citations = match_arxiv_ids_to_library(citations, supabase, request.user_id)
                    citation_rows = [
                        {
                            'source_summary_id': new_id,
                            'cited_arxiv_id': c.get('cited_arxiv_id'),
                            'cited_title': c.get('cited_title'),
                            'year': c.get('year'),
                            'confidence': c.get('confidence', 0.7),
                        }
                        for c in citations[:100]
                    ]
                    if citation_rows:
                        supabase.table('paper_citations').insert(citation_rows).execute()
                    infer_lineage_from_citations(new_id, citations, supabase)
                    infer_lineage_from_similarity(new_id, supabase)
            except Exception:
                pass

            # Log activity
            supabase.table('user_activity').insert({
                'user_id': request.user_id,
                'activity_type': 'summarize',
                'activity_data': {
                    'summary_id': new_id,
                    'paper_title': summary_data['paper_title'],
                    'arxiv_id': arxiv_id,
                    'processing_time': processing_time
                },
                'created_at': datetime.utcnow().isoformat()
            }).execute()

            return jsonify({
                'message': 'Paper processed successfully',
                'summary_id': new_id,
                'summary': result.data[0],
                'processing_time': processing_time
            }), 201
            
        finally:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Failed to process arXiv paper: {str(e)}'}), 500
