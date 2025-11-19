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

# Add parent directory to path to import main.py
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from main import EnhancedResearchPaperSummarizer

process_bp = Blueprint('process', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
        
        # Save file to temporary location
        filename = secure_filename(file.filename)
        temp_dir = Path(tempfile.gettempdir())
        temp_path = temp_dir / filename
        file.save(str(temp_path))
        
        try:
            # Process the paper
            start_time = time.time()
            summarizer = EnhancedResearchPaperSummarizer()
            summary_result = summarizer.summarize_paper(str(temp_path))
            processing_time = time.time() - start_time
            
            # Prepare summary data for database
            summary_data = {
                'user_id': request.user_id,
                'paper_title': summary_result.get('title', filename),
                'paper_authors': summary_result.get('authors', []),
                'paper_url': summary_result.get('pdf_url'),
                'arxiv_id': summary_result.get('arxiv_id'),
                'summary_data': {
                    'overall_summary': summary_result.get('overall_summary', ''),
                    'section_summaries': summary_result.get('section_summaries', {}),
                    'section_keywords': summary_result.get('section_keywords', {}),
                    'overall_keywords': summary_result.get('overall_keywords', []),
                    'entities': summary_result.get('entities', {}),
                    'methodology_flowchart': summary_result.get('methodology_flowchart'),
                    'sections_found': summary_result.get('sections_found', []),
                    'abstract_original': summary_result.get('abstract_original', '')
                },
                'model_used': 'LED-base-16384',
                'processing_time_seconds': round(processing_time, 2),
                'word_count': summary_result.get('num_words_summary', 0),
                'created_at': datetime.utcnow().isoformat()
            }
            
            # Save to database
            result = supabase.table('summaries').insert(summary_data).execute()
            
            if not result.data:
                return jsonify({'error': 'Failed to save summary'}), 500
            
            # Log activity
            supabase.table('user_activity').insert({
                'user_id': request.user_id,
                'activity_type': 'summarize',
                'activity_data': {
                    'summary_id': result.data[0]['id'], 
                    'paper_title': summary_data['paper_title'],
                    'processing_time': processing_time
                },
                'created_at': datetime.utcnow().isoformat()
            }).execute()
            
            return jsonify({
                'message': 'Paper processed successfully',
                'summary_id': result.data[0]['id'],
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
            # Process the paper
            start_time = time.time()
            summarizer = EnhancedResearchPaperSummarizer()
            summary_result = summarizer.summarize_paper(str(temp_path))
            processing_time = time.time() - start_time
            
            # Prepare summary data
            summary_data = {
                'user_id': request.user_id,
                'paper_title': paper.title,
                'paper_authors': [author.name for author in paper.authors],
                'paper_url': paper.pdf_url,
                'arxiv_id': arxiv_id,
                'summary_data': {
                    'overall_summary': summary_result.get('overall_summary', ''),
                    'section_summaries': summary_result.get('section_summaries', {}),
                    'section_keywords': summary_result.get('section_keywords', {}),
                    'overall_keywords': summary_result.get('overall_keywords', []),
                    'entities': summary_result.get('entities', {}),
                    'methodology_flowchart': summary_result.get('methodology_flowchart'),
                    'sections_found': summary_result.get('sections_found', []),
                    'abstract_original': paper.summary
                },
                'model_used': 'LED-base-16384',
                'processing_time_seconds': round(processing_time, 2),
                'word_count': summary_result.get('num_words_summary', 0),
                'created_at': datetime.utcnow().isoformat()
            }
            
            # Save to database
            result = supabase.table('summaries').insert(summary_data).execute()
            
            if not result.data:
                return jsonify({'error': 'Failed to save summary'}), 500
            
            # Log activity
            supabase.table('user_activity').insert({
                'user_id': request.user_id,
                'activity_type': 'summarize',
                'activity_data': {
                    'summary_id': result.data[0]['id'],
                    'paper_title': summary_data['paper_title'],
                    'arxiv_id': arxiv_id,
                    'processing_time': processing_time
                },
                'created_at': datetime.utcnow().isoformat()
            }).execute()
            
            return jsonify({
                'message': 'Paper processed successfully',
                'summary_id': result.data[0]['id'],
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
