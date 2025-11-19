"""Professional Streamlit App for Enhanced Research Paper Summarizer.

Features:
- Clean, modern UI with tabs and sections
- Real-time progress tracking
- Interactive visualizations
- Export capabilities
- Session state management
"""

import archives.streamlit as st
import json
from pathlib import Path
import pandas as pd
from datetime import datetime
import base64
import io

# Optional plotly import
try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    st.warning("⚠️ Plotly not installed. Install with: pip install plotly")

# BERT score import
try:
    from bert_score import score as bert_score_func
    HAS_BERT_SCORE = True
except ImportError:
    HAS_BERT_SCORE = False
    bert_score_func = None

import torch

# Import from main.py
from main import (
    ArxivDatasetFetcher,
    EnhancedResearchPaperSummarizer,
    AdvancedSectionExtractor,
    EnhancedEntityExtractor,
    FlowchartGenerator,
    HierarchicalSummarizer
)


# Page configuration
st.set_page_config(
    page_title="Research Paper Summarizer",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        padding: 0px 24px;
        background-color: #f0f2f6;
        border-radius: 8px 8px 0px 0px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #ff4b4b;
        color: white;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .section-header {
        color: #ff4b4b;
        font-size: 1.5rem;
        font-weight: 600;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    .keyword-badge {
        background-color: #e8f4f8;
        color: #1f77b4;
        padding: 5px 12px;
        border-radius: 15px;
        margin: 3px;
        display: inline-block;
        font-size: 0.9rem;
    }
    .entity-badge {
        background-color: #fff3cd;
        color: #856404;
        padding: 5px 12px;
        border-radius: 15px;
        margin: 3px;
        display: inline-block;
        font-size: 0.9rem;
    }
    </style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables."""
    if 'papers' not in st.session_state:
        st.session_state.papers = []
    if 'summaries' not in st.session_state:
        st.session_state.summaries = []
    if 'current_paper_idx' not in st.session_state:
        st.session_state.current_paper_idx = 0
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    if 'summarizer' not in st.session_state:
        st.session_state.summarizer = None
    if 'uploaded_papers' not in st.session_state:
        st.session_state.uploaded_papers = []
    if 'uploaded_summaries' not in st.session_state:
        st.session_state.uploaded_summaries = []


def render_sidebar():
    """Render sidebar with search options."""
    st.sidebar.title("📚 Paper Summarizer")
    st.sidebar.markdown("---")
    
    # PDF Upload Section
    st.sidebar.subheader("📤 Upload PDF")
    uploaded_file = st.sidebar.file_uploader(
        "Upload a research paper PDF",
        type=['pdf'],
        help="Upload your own PDF to summarize"
    )
    
    if uploaded_file is not None:
        if st.sidebar.button("📄 Process Uploaded PDF", use_container_width=True):
            return None, None, False, uploaded_file
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("Search Settings")
    
    # Query input
    query_type = st.sidebar.selectbox(
        "Query Type",
        ["Category", "Author", "Title", "Custom"]
    )
    
    if query_type == "Category":
        category = st.sidebar.selectbox(
            "Category",
            ["cs.LG (Machine Learning)", "cs.CV (Computer Vision)", 
             "cs.CL (Computation & Language)", "cs.AI (Artificial Intelligence)",
             "cs.NE (Neural & Evolutionary Computing)", "stat.ML (Statistics ML)"]
        )
        query = f"cat:{category.split()[0]}"
    elif query_type == "Author":
        author = st.sidebar.text_input("Author Name")
        query = f"au:{author}" if author else "cat:cs.LG"
    elif query_type == "Title":
        title = st.sidebar.text_input("Title Keywords")
        query = f"ti:{title}" if title else "cat:cs.LG"
    else:
        query = st.sidebar.text_input("Custom Query", "cat:cs.LG")
    
    max_results = st.sidebar.slider("Number of Papers", 1, 20, 5)
    
    st.sidebar.markdown("---")
    
    # Action buttons
    col1, col2 = st.sidebar.columns(2)
    search_button = col1.button("🔍 Search", use_container_width=True)
    clear_button = col2.button("🗑️ Clear", use_container_width=True)
    
    if clear_button:
        st.session_state.papers = []
        st.session_state.summaries = []
        st.session_state.uploaded_papers = []
        st.session_state.uploaded_summaries = []
        st.session_state.current_paper_idx = 0
        st.rerun()
    
    return query, max_results, search_button, None


def fetch_papers(query, max_results):
    """Fetch papers from arXiv."""
    with st.spinner("🔍 Searching arXiv..."):
        fetcher = ArxivDatasetFetcher(
            query=query,
            max_results=max_results,
            save_dir="arxiv_papers"
        )
        papers = fetcher.fetch_papers()
        pdf_paths = fetcher.download_pdfs(papers)
        
        # Attach PDF paths to papers
        for paper, pdf_path in zip(papers, pdf_paths):
            paper['pdf_path'] = pdf_path
        
        return papers


def process_uploaded_pdf(uploaded_file, summarizer):
    """Process an uploaded PDF file."""
    try:
        # Save uploaded file temporarily
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        # Create progress container
        progress_container = st.container()
        
        with progress_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Step 1: Extract sections
            status_text.text("📑 Step 1/5: Extracting sections with layout analysis...")
            progress_bar.progress(20)
            
            # Step 2-4 happen inside summarizer
            status_text.text("🤖 Step 2/5: Processing with hierarchical summarization...")
            progress_bar.progress(40)
            
            # Run the summarizer
            summary_data = summarizer.summarize_paper(tmp_path)
            
            status_text.text("🎯 Step 3/5: Extracting entities...")
            progress_bar.progress(60)
            
            status_text.text("🔑 Step 4/5: Generating keywords...")
            progress_bar.progress(80)
            
            status_text.text("✅ Step 5/5: Finalizing summary...")
            progress_bar.progress(100)
            
            # Clear progress indicators
            import time
            time.sleep(0.5)
            progress_bar.empty()
            status_text.empty()
            
            # Add metadata
            summary_data.update({
                "title": uploaded_file.name.replace('.pdf', ''),
                "authors": ["Unknown"],
                "arxiv_id": "uploaded",
                "published": datetime.now().strftime("%Y-%m-%d"),
                "primary_category": "Uploaded",
                "abstract_original": "",
                "pdf_url": "",
                "pdf_path": tmp_path
            })
            
            return summary_data, tmp_path
            
    except Exception as e:
        st.error(f"Error processing uploaded PDF: {e}")
        import traceback
        st.error(traceback.format_exc())
        return None, None


def calculate_bert_score(summary, reference):
    """Calculate BERT F1 score between summary and reference."""
    if not HAS_BERT_SCORE or not bert_score_func:
        return None
    
    if not reference or not summary:
        return None
    
    try:
        with st.spinner("📊 Calculating BERT F1 score..."):
            P, R, F1 = bert_score_func(
                [summary],
                [reference],
                lang='en',
                verbose=False,
                device='cuda' if torch.cuda.is_available() else 'cpu'
            )
            return {
                'precision': float(P[0]),
                'recall': float(R[0]),
                'f1': float(F1[0])
            }
    except Exception as e:
        st.warning(f"BERT score calculation failed: {e}")
        return None


def process_paper(paper, summarizer, calculate_bert=True):
    """Process a single paper and generate summary with progress tracking."""
    try:
        # Create progress container
        progress_container = st.container()
        
        with progress_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Step 1: Extract sections
            status_text.text("📑 Step 1/5: Extracting sections with layout analysis...")
            progress_bar.progress(20)
            
            # Step 2-4 happen inside summarizer (can't track easily)
            status_text.text("🤖 Step 2/5: Processing with hierarchical summarization...")
            progress_bar.progress(40)
            
            # Actually run the summarizer
            summary_data = summarizer.summarize_paper(paper['pdf_path'])
            
            status_text.text("🎯 Step 3/5: Extracting entities...")
            progress_bar.progress(60)
            
            status_text.text("🔑 Step 4/5: Generating keywords...")
            progress_bar.progress(80)
            
            # Calculate BERT score if reference available
            if calculate_bert and paper.get("summary") and HAS_BERT_SCORE:
                status_text.text("📊 Step 5/5: Calculating BERT F1 score...")
                bert_scores = calculate_bert_score(
                    summary_data['overall_summary'],
                    paper['summary']
                )
                if bert_scores:
                    summary_data.update(bert_scores)
            
            status_text.text("✅ Finalizing summary...")
            progress_bar.progress(100)
            
            # Clear progress indicators after short delay
            import time
            time.sleep(0.5)
            progress_bar.empty()
            status_text.empty()
            
            summary_data.update({
            "title": paper["title"],
            "authors": paper["authors"],
            "arxiv_id": paper["arxiv_id"],
            "published": paper["published"],
            "primary_category": paper.get("primary_category", ""),
            "abstract_original": paper.get("summary", ""),
            "pdf_url": paper.get("pdf_url", ""),
        })
        return summary_data
    except Exception as e:
        st.error(f"Error processing paper: {e}")
        return None


def render_paper_card(paper, idx):
    """Render a paper card with basic info."""
    with st.container():
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.markdown(f"### {idx + 1}. {paper['title']}")
            st.markdown(f"**Authors:** {', '.join(paper['authors'][:3])}{'...' if len(paper['authors']) > 3 else ''}")
            st.markdown(f"**Published:** {paper['published'][:10]} | **Category:** {paper.get('primary_category', 'N/A')}")
        
        with col2:
            if st.button("📄 Summarize", key=f"summarize_{idx}", use_container_width=True):
                return True
    
    st.markdown("---")
    return False


def render_summary_overview(summary):
    """Render summary overview with metrics."""
    st.markdown('<div class="section-header">📊 Summary Overview</div>', unsafe_allow_html=True)
    
    # Check if BERT scores are available
    has_bert_scores = 'f1' in summary
    
    if has_bert_scores:
        col1, col2, col3, col4, col5 = st.columns(5)
    else:
        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 0.1])
    
    with col1:
        st.metric(
            "Original Words",
            f"{summary['num_words_original']:,}",
            delta=None
        )
    
    with col2:
        st.metric(
            "Summary Words",
            f"{summary['num_words_summary']:,}",
            delta=None
        )
    
    with col3:
        compression_ratio = (1 - summary['num_words_summary'] / summary['num_words_original']) * 100
        st.metric(
            "Compression",
            f"{compression_ratio:.1f}%",
            delta=None
        )
    
    with col4:
        st.metric(
            "Sections Found",
            len(summary['sections_found']),
            delta=None
        )
    
    if has_bert_scores:
        with col5:
            st.metric(
                "BERT F1 Score",
                f"{summary['f1']:.3f}",
                delta=None,
                help="BERT F1 score comparing generated summary with original abstract"
            )
    
    # Display detailed BERT scores if available
    if has_bert_scores:
        st.markdown("")
        st.markdown("**📊 BERT Score Details** (Comparison with Original Abstract)")
        bert_col1, bert_col2, bert_col3 = st.columns(3)
        
        with bert_col1:
            st.info(f"**Precision:** {summary.get('precision', 0):.4f}")
        with bert_col2:
            st.info(f"**Recall:** {summary.get('recall', 0):.4f}")
        with bert_col3:
            st.info(f"**F1 Score:** {summary.get('f1', 0):.4f}")
        
        # Add explanation
        with st.expander("ℹ️ What is BERT F1 Score?"):
            st.write("""
            **BERT F1 Score** measures the semantic similarity between the generated summary and the original abstract using BERT embeddings.
            
            - **Precision**: How much of the generated summary content is relevant to the reference
            - **Recall**: How much of the reference content is captured in the summary
            - **F1 Score**: Harmonic mean of precision and recall (0-1, higher is better)
            
            **Interpretation:**
            - F1 > 0.9: Excellent semantic alignment
            - F1 > 0.8: Good semantic alignment
            - F1 > 0.7: Moderate semantic alignment
            - F1 < 0.7: Low semantic alignment
            
            *Note: This score only appears for arXiv papers where we have the original abstract.*
            """)
    elif HAS_BERT_SCORE and summary.get('abstract_original'):
        st.info("💡 Enable BERT score calculation for quality evaluation")
    elif not HAS_BERT_SCORE:
        st.warning("⚠️ Install bert-score for quality metrics: `pip install bert-score`")


def render_entities_section(entities):
    """Render extracted entities with visual badges."""
    st.markdown('<div class="section-header">🎯 Extracted Entities</div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**📊 Datasets**")
        if entities['datasets']:
            for dataset in entities['datasets'][:8]:
                st.markdown(f'<span class="entity-badge">{dataset}</span>', unsafe_allow_html=True)
        else:
            st.info("No datasets detected")
    
    with col2:
        st.markdown("**🤖 Models**")
        if entities['models']:
            for model in entities['models'][:8]:
                st.markdown(f'<span class="entity-badge">{model}</span>', unsafe_allow_html=True)
        else:
            st.info("No models detected")
    
    with col3:
        st.markdown("**📈 Metrics**")
        if entities['metrics']:
            for metric in entities['metrics'][:8]:
                st.markdown(f'<span class="entity-badge">{metric}</span>', unsafe_allow_html=True)
        else:
            st.info("No metrics detected")


def render_keywords_section(keywords, section_keywords):
    """Render keywords with visual representation."""
    st.markdown('<div class="section-header">🔑 Keywords Analysis</div>', unsafe_allow_html=True)
    
    # Overall keywords
    st.markdown("**Overall Keywords**")
    if keywords:
        for kw in keywords:
            st.markdown(f'<span class="keyword-badge">{kw}</span>', unsafe_allow_html=True)
    
    st.markdown("")
    
    # Section-specific keywords
    if section_keywords:
        cols = st.columns(len(section_keywords))
        for idx, (section, kws) in enumerate(section_keywords.items()):
            with cols[idx]:
                st.markdown(f"**{section.title()}**")
                for kw in kws[:5]:
                    st.markdown(f'<span class="keyword-badge" style="font-size: 0.8rem;">{kw}</span>', unsafe_allow_html=True)


def render_section_summaries(section_summaries):
    """Render per-section summaries in expandable sections."""
    st.markdown('<div class="section-header">📑 Section Summaries</div>', unsafe_allow_html=True)
    
    section_icons = {
        'introduction': '🎯',
        'methodology': '⚙️',
        'experiments': '🧪',
        'results': '📊',
        'discussion': '💬',
        'conclusion': '🎓',
        'abstract': '📝',
        'related_work': '📚'
    }
    
    if not section_summaries:
        st.warning("No section summaries available")
        return
    
    for section, summary in section_summaries.items():
        icon = section_icons.get(section, '📄')
        section_display = section.replace('_', ' ').title()
        with st.expander(f"{icon} {section_display}", expanded=(section == 'introduction')):
            st.write(summary)
            
            # Show word count
            word_count = len(summary.split())
            st.caption(f"📊 {word_count} words")


def render_flowchart(flowchart):
    """Render methodology flowchart."""
    st.markdown('<div class="section-header">🔄 Methodology Flowchart</div>', unsafe_allow_html=True)
    
    if flowchart:
        # Display the flowchart code
        with st.expander("📋 View Mermaid Code", expanded=False):
            st.code(flowchart, language="mermaid")
        
        # Try to render using mermaid (if available in future Streamlit versions)
        st.markdown(f"""
        ```mermaid
        {flowchart}
        ```
        """)
        
        # Provide links for viewing
        col1, col2 = st.columns(2)
        with col1:
            st.link_button("🌐 View in Mermaid Live", "https://mermaid.live", use_container_width=True)
        with col2:
            # Create a copy button alternative
            st.info("💡 Copy the code above to visualize the flowchart")
    else:
        st.warning("⚠️ No flowchart generated. The methodology section might not contain enough process steps.")
        st.info("💡 Flowcharts are generated when the methodology section contains process verbs like: train, test, evaluate, implement, etc.")


def create_keyword_chart(section_keywords):
    """Create a bar chart of keywords per section."""
    if not section_keywords or not HAS_PLOTLY:
        return None
    
    data = []
    for section, keywords in section_keywords.items():
        for kw in keywords:
            data.append({'Section': section.title(), 'Keyword': kw, 'Count': 1})
    
    if not data:
        return None
    
    df = pd.DataFrame(data)
    fig = px.bar(
        df.groupby('Section').size().reset_index(name='Keywords'),
        x='Section',
        y='Keywords',
        title='Keywords Distribution Across Sections',
        color='Section'
    )
    fig.update_layout(showlegend=False)
    return fig


def export_summary(summary, format='json'):
    """Export summary in various formats."""
    if format == 'json':
        return json.dumps(summary, indent=2)
    elif format == 'markdown':
        md = f"# {summary['title']}\n\n"
        md += f"**Authors:** {', '.join(summary['authors'])}\n\n"
        md += f"**Published:** {summary['published']}\n\n"
        md += f"## Summary\n\n{summary['overall_summary']}\n\n"
        md += f"## Keywords\n\n{', '.join(summary['overall_keywords'])}\n\n"
        
        if summary.get('entities'):
            md += f"## Entities\n\n"
            md += f"- **Datasets:** {', '.join(summary['entities']['datasets'])}\n"
            md += f"- **Models:** {', '.join(summary['entities']['models'])}\n"
            md += f"- **Metrics:** {', '.join(summary['entities']['metrics'])}\n\n"
        
        if summary.get('section_summaries'):
            md += f"## Section Summaries\n\n"
            for section, text in summary['section_summaries'].items():
                md += f"### {section.title()}\n\n{text}\n\n"
        
        return md


def main():
    """Main application."""
    init_session_state()
    
    # Sidebar
    query, max_results, search_button, uploaded_file = render_sidebar()
    
    # Main content
    st.title("📚 Advanced Research Paper Summarizer")
    st.markdown("**AI-powered hierarchical summarization with advanced section detection and entity extraction**")
    st.markdown("*Features: Font-based section extraction • LED long-context summarization • Entity recognition • BERT F1 evaluation*")
    st.markdown("---")
    
    # Handle uploaded PDF
    if uploaded_file is not None:
        st.info(f"📄 Uploaded file: **{uploaded_file.name}**")
        
        # Initialize summarizer if not done
        if st.session_state.summarizer is None:
            with st.spinner("🔧 Loading AI models..."):
                st.session_state.summarizer = EnhancedResearchPaperSummarizer()
        
        # Process uploaded PDF
        with st.spinner(f"🤖 Processing uploaded PDF: {uploaded_file.name}..."):
            summary, tmp_path = process_uploaded_pdf(uploaded_file, st.session_state.summarizer)
            
            if summary:
                # Store in uploaded papers
                if summary not in st.session_state.uploaded_summaries:
                    st.session_state.uploaded_summaries.append(summary)
                    st.success("✅ PDF processed successfully!")
                
                # Display summary
                st.markdown("---")
                st.markdown(f"## 📄 {summary['title']}")
                
                # Tabs for different views
                summary_tabs = st.tabs([
                    "📊 Overview",
                    "📝 Summaries",
                    "🎯 Entities",
                    "🔑 Keywords",
                    "🔄 Flowchart",
                    "📤 Export"
                ])
                
                with summary_tabs[0]:
                    render_summary_overview(summary)
                    
                    # Show detected sections
                    if summary.get('sections_found'):
                        st.markdown("**📑 Detected Sections**")
                        sections_str = " → ".join([s.replace('_', ' ').title() for s in summary['sections_found']])
                        st.success(sections_str)
                    
                    st.markdown("")
                    st.markdown("**📝 Overall Summary**")
                    st.info(summary['overall_summary'])
                    
                    # Visualization
                    if HAS_PLOTLY:
                        chart = create_keyword_chart(summary.get('section_keywords', {}))
                        if chart:
                            st.plotly_chart(chart, use_container_width=True)
                
                with summary_tabs[1]:
                    render_section_summaries(summary.get('section_summaries', {}))
                
                with summary_tabs[2]:
                    render_entities_section(summary.get('entities', {}))
                
                with summary_tabs[3]:
                    render_keywords_section(
                        summary.get('overall_keywords', []),
                        summary.get('section_keywords', {})
                    )
                
                with summary_tabs[4]:
                    render_flowchart(summary.get('methodology_flowchart'))
                
                with summary_tabs[5]:
                    st.markdown("### Export Summary")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        export_format = st.selectbox("Format", ["JSON", "Markdown"])
                    with col2:
                        st.metric("Sections Detected", len(summary.get('sections_found', [])))
                    
                    format_key = export_format.lower()
                    export_content = export_summary(summary, format_key)
                    
                    st.download_button(
                        label=f"📥 Download as {export_format}",
                        data=export_content,
                        file_name=f"summary_{uploaded_file.name.replace('.pdf', '')}.{format_key if format_key != 'markdown' else 'md'}",
                        mime=f"application/{format_key}" if format_key == 'json' else "text/markdown"
                    )
                    
                    st.code(export_content, language=format_key)
                
                # Clean up temp file
                import os
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except:
                        pass
        
        return  # Don't show arXiv search results when processing uploaded file
    
    # Search action
    if search_button:
        papers = fetch_papers(query, max_results)
        if papers:
            st.session_state.papers = papers
            st.session_state.summaries = [None] * len(papers)
            st.success(f"✅ Found {len(papers)} papers!")
    
    # Display papers
    if st.session_state.papers:
        tab1, tab2 = st.tabs(["📋 Paper List", "📊 Batch Analysis"])
        
        with tab1:
            # Paper list
            for idx, paper in enumerate(st.session_state.papers):
                if render_paper_card(paper, idx):
                    st.session_state.current_paper_idx = idx
                    
                    # Initialize summarizer if not done
                    if st.session_state.summarizer is None:
                        with st.spinner("🔧 Loading AI models..."):
                            st.session_state.summarizer = EnhancedResearchPaperSummarizer()
                    
                    # Process paper
                    with st.spinner(f"🤖 Processing paper {idx + 1}..."):
                        summary = process_paper(paper, st.session_state.summarizer)
                        if summary:
                            st.session_state.summaries[idx] = summary
                            st.rerun()
            
            # Display summary if available
            current_idx = st.session_state.current_paper_idx
            if st.session_state.summaries[current_idx]:
                summary = st.session_state.summaries[current_idx]
                
                st.markdown("---")
                st.markdown(f"## 📄 {summary['title']}")
                
                # Tabs for different views
                summary_tabs = st.tabs([
                    "📊 Overview",
                    "📝 Summaries",
                    "🎯 Entities",
                    "🔑 Keywords",
                    "🔄 Flowchart",
                    "📤 Export"
                ])
                
                with summary_tabs[0]:
                    render_summary_overview(summary)
                    
                    # Show detected sections
                    if summary.get('sections_found'):
                        st.markdown("**📑 Detected Sections**")
                        sections_str = " → ".join([s.replace('_', ' ').title() for s in summary['sections_found']])
                        st.success(sections_str)
                    
                    st.markdown("")
                    st.markdown("**📝 Overall Summary**")
                    st.info(summary['overall_summary'])
                    
                    # Visualization (only if plotly available)
                    if HAS_PLOTLY:
                        chart = create_keyword_chart(summary.get('section_keywords', {}))
                        if chart:
                            st.plotly_chart(chart, use_container_width=True)
                    else:
                        st.info("💡 Install plotly for keyword visualizations: pip install plotly")
                
                with summary_tabs[1]:
                    render_section_summaries(summary.get('section_summaries', {}))
                
                with summary_tabs[2]:
                    render_entities_section(summary.get('entities', {}))
                
                with summary_tabs[3]:
                    render_keywords_section(
                        summary.get('overall_keywords', []),
                        summary.get('section_keywords', {})
                    )
                
                with summary_tabs[4]:
                    render_flowchart(summary.get('methodology_flowchart'))
                
                with summary_tabs[5]:
                    st.markdown("### Export Summary")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        export_format = st.selectbox("Format", ["JSON", "Markdown"])
                    with col2:
                        st.metric("Sections Detected", len(summary.get('sections_found', [])))
                    
                    format_key = export_format.lower()
                    export_content = export_summary(summary, format_key)
                    
                    st.download_button(
                        label=f"📥 Download as {export_format}",
                        data=export_content,
                        file_name=f"summary_{summary['arxiv_id']}.{format_key if format_key != 'markdown' else 'md'}",
                        mime=f"application/{format_key}" if format_key == 'json' else "text/markdown"
                    )
                    
                    st.code(export_content, language=format_key)
        
        with tab2:
            st.markdown("### Batch Analysis")
            
            # Process all button
            if st.button("🚀 Process All Papers", use_container_width=True):
                if st.session_state.summarizer is None:
                    with st.spinner("🔧 Loading AI models..."):
                        st.session_state.summarizer = EnhancedResearchPaperSummarizer()
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, paper in enumerate(st.session_state.papers):
                    if st.session_state.summaries[idx] is None:
                        status_text.text(f"Processing paper {idx + 1}/{len(st.session_state.papers)}: {paper['title'][:50]}...")
                        summary = process_paper(paper, st.session_state.summarizer)
                        if summary:
                            st.session_state.summaries[idx] = summary
                        progress_bar.progress((idx + 1) / len(st.session_state.papers))
                
                status_text.text("✅ All papers processed!")
                st.success("Batch processing complete!")
            
            # Display comparison
            processed_summaries = [s for s in st.session_state.summaries if s is not None]
            
            if processed_summaries:
                st.markdown("---")
                st.markdown("### 📊 Comparative Analysis")
                
                # Create comparison dataframe
                comparison_data = []
                for summary in processed_summaries:
                    row = {
                        'Title': summary['title'][:50] + '...',
                        'Words (Original)': summary['num_words_original'],
                        'Words (Summary)': summary['num_words_summary'],
                        'Compression %': f"{(1 - summary['num_words_summary'] / summary['num_words_original']) * 100:.1f}%",
                        'Sections': len(summary['sections_found']),
                        'Keywords': len(summary['overall_keywords']),
                        'Datasets': len(summary['entities']['datasets']),
                        'Models': len(summary['entities']['models'])
                    }
                    # Add BERT F1 if available
                    if 'f1' in summary:
                        row['BERT F1'] = f"{summary['f1']:.3f}"
                    comparison_data.append(row)
                
                df = pd.DataFrame(comparison_data)
                st.dataframe(df, use_container_width=True)
                
                # Export all summaries
                if st.button("📥 Export All Summaries", use_container_width=True):
                    all_summaries_json = json.dumps(processed_summaries, indent=2)
                    st.download_button(
                        label="Download All (JSON)",
                        data=all_summaries_json,
                        file_name=f"all_summaries_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json"
                    )
    
    else:
        # Welcome screen
        st.info("👈 Use the sidebar to search for papers on arXiv")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("### 🎯 Features")
            st.markdown("""
            - Font-based section detection
            - Hierarchical summarization
            - LED long-context model
            - Advanced entity extraction
            - Keyword analysis
            - Flowchart generation
            - **PDF upload support**
            - **BERT F1 score evaluation**
            """)
        
        with col2:
            st.markdown("### 🚀 How to Use")
            st.markdown("""
            1. **Upload PDF** or search arXiv
            2. Click 'Search' or 'Process' button
            3. Choose a paper to summarize
            4. View BERT F1 scores
            5. Explore results in tabs
            6. Export as needed
            """)
        
        with col3:
            st.markdown("### 💡 Tips")
            st.markdown("""
            - Upload your own PDFs
            - Start with 5-10 papers
            - Use specific categories
            - Try batch processing
            - Check BERT F1 scores
            - Export for later review
            - View flowcharts in Mermaid
            """)
    
    # Footer
    st.markdown("---")
    st.markdown(
        "<div style='text-align: center; color: #666;'>" 
        "Built with Streamlit | Powered by LED & SciBERT | BERT F1 Evaluation | Optimized for RTX 2050 4GB"
        "</div>",
        unsafe_allow_html=True
    )
if __name__ == "__main__":
    main()