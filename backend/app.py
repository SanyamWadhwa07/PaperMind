"""Flask Backend API for Research Paper Summarizer.

Professional REST API with endpoints for:
- Paper search and fetching from arXiv
- PDF upload and processing
- Summarization with progress tracking
- Entity extraction and keyword analysis
- Export functionality
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
import json
import traceback
from pathlib import Path
import tempfile
from datetime import datetime
import threading
import uuid

# Import authentication routes
from auth.routes import auth_bp
from routes.summaries import summaries_bp
from routes.process_paper import process_bp
from routes.profile import profile_bp

# Import from main.py
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from main import (
    ArxivDatasetFetcher,
    EnhancedResearchPaperSummarizer,
    AdvancedSectionExtractor,
    EnhancedEntityExtractor,
    FlowchartGenerator,
    HierarchicalSummarizer
)

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Register blueprints for authentication and user routes
app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(summaries_bp, url_prefix='/api')
app.register_blueprint(process_bp, url_prefix='/api')
app.register_blueprint(profile_bp, url_prefix='/api')

# Configuration
UPLOAD_FOLDER = Path('uploads')
SUMMARIES_FOLDER = Path('summaries_api')
ARXIV_FOLDER = Path('arxiv_papers')
ALLOWED_EXTENSIONS = {'pdf'}

UPLOAD_FOLDER.mkdir(exist_ok=True)
SUMMARIES_FOLDER.mkdir(exist_ok=True)
ARXIV_FOLDER.mkdir(exist_ok=True)

app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Global state for summarizer (singleton pattern)
summarizer = None
processing_status = {}


def get_summarizer():
    """Get or create summarizer instance."""
    global summarizer
    if summarizer is None:
        summarizer = EnhancedResearchPaperSummarizer()
    return summarizer


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'research-paper-summarizer-api',
        'version': '1.0.0'
    })


@app.route('/api/search', methods=['POST'])
def search_papers():
    """Search and fetch papers from arXiv.
    
    Request body:
    {
        "query": "cat:cs.LG",
        "max_results": 5
    }
    """
    try:
        data = request.get_json()
        query = data.get('query', 'cat:cs.LG')
        max_results = data.get('max_results', 5)
        
        # Validate max_results
        if max_results > 20:
            return jsonify({
                'error': 'max_results cannot exceed 20'
            }), 400
        
        # Fetch papers
        fetcher = ArxivDatasetFetcher(
            query=query,
            max_results=max_results,
            save_dir=str(ARXIV_FOLDER)
        )
        
        papers = fetcher.fetch_papers()
        pdf_paths = fetcher.download_pdfs(papers)
        
        # Attach PDF paths
        for paper, pdf_path in zip(papers, pdf_paths):
            paper['pdf_path'] = pdf_path
        
        return jsonify({
            'success': True,
            'count': len(papers),
            'papers': papers
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/upload', methods=['POST'])
def upload_pdf():
    """Upload a PDF file for processing.
    
    Multipart form data with 'file' field.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Only PDF files allowed'}), 400
        
        # Save file
        filename = secure_filename(file.filename)
        file_id = str(uuid.uuid4())
        filepath = UPLOAD_FOLDER / f"{file_id}_{filename}"
        file.save(filepath)
        
        return jsonify({
            'success': True,
            'file_id': file_id,
            'filename': filename,
            'filepath': str(filepath)
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/summarize', methods=['POST'])
def summarize_paper():
    """Summarize a paper (from arXiv or uploaded).
    
    Request body:
    {
        "pdf_path": "/path/to/paper.pdf",
        "title": "Paper Title (optional)",
        "authors": ["Author 1"],
        "arxiv_id": "2511.12345v1 (optional)"
    }
    """
    try:
        data = request.get_json()
        pdf_path = data.get('pdf_path')
        
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({'error': 'Invalid PDF path'}), 400
        
        # Get or create summarizer
        summ = get_summarizer()
        
        # Process paper
        summary_data = summ.summarize_paper(pdf_path)
        
        # Add metadata
        summary_data.update({
            'title': data.get('title', Path(pdf_path).stem),
            'authors': data.get('authors', []),
            'arxiv_id': data.get('arxiv_id', 'uploaded'),
            'published': data.get('published', datetime.now().strftime('%Y-%m-%d')),
            'primary_category': data.get('primary_category', 'Unknown'),
            'abstract_original': data.get('abstract', ''),
            'pdf_path': pdf_path
        })
        
        # Save summary
        summary_id = str(uuid.uuid4())
        summary_file = SUMMARIES_FOLDER / f"summary_{summary_id}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2)
        
        summary_data['summary_id'] = summary_id
        
        return jsonify({
            'success': True,
            'summary': summary_data
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/summarize/async', methods=['POST'])
def summarize_paper_async():
    """Start async summarization process.
    
    Returns a task_id to check status.
    """
    try:
        data = request.get_json()
        pdf_path = data.get('pdf_path')
        
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({'error': 'Invalid PDF path'}), 400
        
        task_id = str(uuid.uuid4())
        
        # Initialize status
        processing_status[task_id] = {
            'status': 'processing',
            'progress': 0,
            'message': 'Starting...',
            'result': None,
            'error': None
        }
        
        # Start background thread
        def process_in_background():
            try:
                summ = get_summarizer()
                
                processing_status[task_id].update({
                    'progress': 20,
                    'message': 'Extracting sections...'
                })
                
                summary_data = summ.summarize_paper(pdf_path)
                
                processing_status[task_id].update({
                    'progress': 80,
                    'message': 'Finalizing...'
                })
                
                # Add metadata
                summary_data.update({
                    'title': data.get('title', Path(pdf_path).stem),
                    'authors': data.get('authors', []),
                    'arxiv_id': data.get('arxiv_id', 'uploaded'),
                    'published': data.get('published', datetime.now().strftime('%Y-%m-%d')),
                    'primary_category': data.get('primary_category', 'Unknown'),
                    'abstract_original': data.get('abstract', ''),
                    'pdf_path': pdf_path
                })
                
                # Save summary
                summary_id = str(uuid.uuid4())
                summary_file = SUMMARIES_FOLDER / f"summary_{summary_id}.json"
                with open(summary_file, 'w', encoding='utf-8') as f:
                    json.dump(summary_data, f, indent=2)
                
                summary_data['summary_id'] = summary_id
                
                processing_status[task_id].update({
                    'status': 'completed',
                    'progress': 100,
                    'message': 'Complete',
                    'result': summary_data
                })
                
            except Exception as e:
                processing_status[task_id].update({
                    'status': 'error',
                    'progress': 0,
                    'message': str(e),
                    'error': traceback.format_exc()
                })
        
        thread = threading.Thread(target=process_in_background)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'task_id': task_id
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/status/<task_id>', methods=['GET'])
def get_processing_status(task_id):
    """Get status of async processing task."""
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify(processing_status[task_id])


@app.route('/api/summaries', methods=['GET'])
def list_summaries():
    """List all saved summaries."""
    try:
        summaries = []
        for file in SUMMARIES_FOLDER.glob('summary_*.json'):
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                summaries.append({
                    'summary_id': file.stem.replace('summary_', ''),
                    'title': data.get('title'),
                    'authors': data.get('authors', [])[:3],
                    'arxiv_id': data.get('arxiv_id'),
                    'published': data.get('published'),
                    'sections': len(data.get('sections_found', []))
                })
        
        return jsonify({
            'success': True,
            'count': len(summaries),
            'summaries': summaries
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/summary/<summary_id>', methods=['GET'])
def get_summary(summary_id):
    """Get a specific summary by ID."""
    try:
        summary_file = SUMMARIES_FOLDER / f"summary_{summary_id}.json"
        
        if not summary_file.exists():
            return jsonify({'error': 'Summary not found'}), 404
        
        with open(summary_file, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)
        
        return jsonify({
            'success': True,
            'summary': summary_data
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/export/<summary_id>', methods=['GET'])
def export_summary(summary_id):
    """Export summary as JSON or Markdown.
    
    Query params: format=json|markdown
    """
    try:
        format_type = request.args.get('format', 'json')
        summary_file = SUMMARIES_FOLDER / f"summary_{summary_id}.json"
        
        if not summary_file.exists():
            return jsonify({'error': 'Summary not found'}), 404
        
        with open(summary_file, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)
        
        if format_type == 'markdown':
            # Convert to markdown
            md = f"# {summary_data['title']}\n\n"
            md += f"**Authors:** {', '.join(summary_data['authors'])}\n\n"
            md += f"**Published:** {summary_data['published']}\n\n"
            md += f"**Category:** {summary_data.get('primary_category', 'N/A')}\n\n"
            
            md += f"## Summary\n\n{summary_data['overall_summary']}\n\n"
            
            md += f"## Keywords\n\n{', '.join(summary_data['overall_keywords'])}\n\n"
            
            if summary_data.get('entities'):
                md += f"## Entities\n\n"
                md += f"- **Datasets:** {', '.join(summary_data['entities']['datasets'])}\n"
                md += f"- **Models:** {', '.join(summary_data['entities']['models'])}\n"
                md += f"- **Metrics:** {', '.join(summary_data['entities']['metrics'])}\n\n"
            
            if summary_data.get('section_summaries'):
                md += f"## Section Summaries\n\n"
                for section, text in summary_data['section_summaries'].items():
                    md += f"### {section.title()}\n\n{text}\n\n"
            
            # Create temp file
            temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md', encoding='utf-8')
            temp_file.write(md)
            temp_file.close()
            
            return send_file(
                temp_file.name,
                as_attachment=True,
                download_name=f"{summary_data['arxiv_id']}.md",
                mimetype='text/markdown'
            )
        else:
            # JSON export
            return jsonify(summary_data)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/batch/summarize', methods=['POST'])
def batch_summarize():
    """Batch summarize multiple papers.
    
    Request body:
    {
        "papers": [
            {"pdf_path": "...", "title": "...", ...},
            ...
        ]
    }
    """
    try:
        data = request.get_json()
        papers = data.get('papers', [])
        
        if not papers:
            return jsonify({'error': 'No papers provided'}), 400
        
        summ = get_summarizer()
        results = []
        
        for paper in papers:
            try:
                pdf_path = paper.get('pdf_path')
                if not pdf_path or not os.path.exists(pdf_path):
                    results.append({'error': 'Invalid PDF path', 'paper': paper})
                    continue
                
                summary_data = summ.summarize_paper(pdf_path)
                summary_data.update({
                    'title': paper.get('title', Path(pdf_path).stem),
                    'authors': paper.get('authors', []),
                    'arxiv_id': paper.get('arxiv_id', 'uploaded'),
                    'published': paper.get('published', datetime.now().strftime('%Y-%m-%d')),
                    'primary_category': paper.get('primary_category', 'Unknown')
                })
                
                results.append({'success': True, 'summary': summary_data})
                
            except Exception as e:
                results.append({
                    'success': False,
                    'error': str(e),
                    'paper': paper
                })
        
        return jsonify({
            'success': True,
            'total': len(papers),
            'completed': sum(1 for r in results if r.get('success')),
            'failed': sum(1 for r in results if not r.get('success')),
            'results': results
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large error."""
    return jsonify({
        'error': 'File too large. Maximum size is 50MB.'
    }), 413


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({
        'error': 'Endpoint not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({
        'error': 'Internal server error',
        'message': str(error)
    }), 500


if __name__ == '__main__':
    print("="*60)
    print("Research Paper Summarizer API")
    print("="*60)
    print(f"Upload folder: {UPLOAD_FOLDER.absolute()}")
    print(f"Summaries folder: {SUMMARIES_FOLDER.absolute()}")
    print(f"ArXiv papers folder: {ARXIV_FOLDER.absolute()}")
    print("="*60)
    print("Starting server on http://localhost:5000")
    print("API Documentation: http://localhost:5000/api/health")
    print("="*60)
    
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
