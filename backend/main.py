"""Enhanced Research Paper Summarizer with Advanced Section Detection.

Optimized for RTX 2050 4GB with:
- Font-based section detection using PDF layout analysis
- Hierarchical summarization (paragraph → section → paper)
- Improved text extraction with column detection
- Better entity extraction with context
- Reference section filtering
- Quality validation at each stage
"""

from pathlib import Path
import argparse
import json
import re
import logging
from typing import Dict, List, Optional, Tuple
import warnings
import string
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from io import BytesIO
import traceback

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

import numpy as np
import nltk
import requests
import torch
import arxiv
import fitz  # PyMuPDF
import pdfplumber
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoTokenizer, AutoModel, pipeline
from transformers import LEDTokenizer, LEDForConditionalGeneration

try:
    from PIL import Image
    import pytesseract
except ImportError:
    Image = None
    pytesseract = None

# Suppress warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*Some weights.*not initialized.*")

try:
    from keybert import KeyBERT
except Exception:
    KeyBERT = None

try:
    from bert_score import score as bert_score
except Exception:
    bert_score = None

# Download required NLTK data
try:
    nltk.download("punkt", quiet=True)
    nltk.download("punkt_tab", quiet=True)
except Exception as e:
    pass  # Continue if downloads fail

# Suppress logs
import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import logging as hf_logging
hf_logging.getLogger("transformers").setLevel(hf_logging.ERROR)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def load_patterns(pattern_file="patterns.json") -> Dict:
    """Load patterns from JSON file with fallback to defaults."""
    try:
        pattern_path = Path(__file__).parent / pattern_file
        if pattern_path.exists():
            with open(pattern_path, 'r', encoding='utf-8') as f:
                patterns = json.load(f)
                logger.info(f"✓ Loaded patterns from {pattern_file}")
                return patterns
    except Exception as e:
        logger.warning(f"Could not load patterns file: {e}. Using defaults.")
    
    # Return empty dict to trigger fallback to hardcoded patterns
    return {}


def load_config(config_file: Optional[str] = None) -> Dict:
    """Load configuration from YAML file if available."""
    if not config_file:
        return {}
    
    if not YAML_AVAILABLE:
        logger.warning("PyYAML not installed. Install with: pip install pyyaml")
        return {}
    
    try:
        config_path = Path(config_file)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                logger.info(f"✓ Loaded config from {config_file}")
                return config or {}
    except Exception as e:
        logger.warning(f"Could not load config file: {e}")
    
    return {}


class ArxivDatasetFetcher:
    def __init__(self, query="all", max_results=2, save_dir="arxiv_papers"):
        self.query = query
        self.max_results = max_results
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def fetch_papers(self):
        logger.info(f"Fetching up to {self.max_results} papers from arXiv for query: '{self.query}'")
        search = arxiv.Search(
            query=self.query,
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        papers = []
        for result in search.results():
            papers.append({
                "title": result.title,
                "authors": [a.name for a in result.authors],
                "summary": result.summary,
                "pdf_url": result.pdf_url,
                "arxiv_id": result.entry_id.split("/")[-1],
                "published": str(result.published),
                "primary_category": getattr(result, "primary_category", ""),
            })
        logger.info(f"Found {len(papers)} papers.")
        return papers

    def download_pdfs(self, papers):
        pdf_paths = []
        for paper in papers:
            pdf_path = self.save_dir / f"{paper['arxiv_id']}.pdf"
            if pdf_path.exists():
                logger.info(f"Already downloaded: {paper['title']}")
                pdf_paths.append(str(pdf_path))
                continue

            try:
                logger.info(f"Downloading: {paper['title']}")
                resp = requests.get(paper["pdf_url"], timeout=30)
                resp.raise_for_status()
                pdf_path.write_bytes(resp.content)
                pdf_paths.append(str(pdf_path))
                logger.info(f"Saved to {pdf_path}")
            except Exception as e:
                logger.warning(f"Failed to download {paper['title']}: {e}")

        return pdf_paths


class AdvancedSectionExtractor:
    """Advanced section extraction using PDF layout analysis and font information."""
    
    SECTION_KEYWORDS = {
        'abstract': ['abstract'],
        'introduction': ['introduction', 'background'],
        'related_work': ['related work', 'literature review', 'prior work', 'previous work'],
        'methodology': ['method', 'methodology', 'approach', 'model', 'architecture', 
                       'proposed method', 'proposed approach', 'our approach', 'our method'],
        'experiments': ['experiment', 'experimental setup', 'experimental results', 
                       'experimental design', 'evaluation setup'],
        'results': ['results', 'findings', 'performance', 'experimental results'],
        'discussion': ['discussion', 'analysis', 'ablation study', 'ablation studies'],
        'conclusion': ['conclusion', 'conclusions', 'concluding remarks', 'future work', 
                      'summary', 'limitations'],
        'references': ['references', 'bibliography', 'works cited'],
    }
    
    # Regex patterns for section headers (fallback when font detection fails)
    SECTION_HEADER_PATTERNS = [
        r'^\d+\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',  # "1. Introduction"
        r'^[A-Z][A-Z\s]{3,30}$',  # "INTRODUCTION" or "RELATED WORK"
        r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4}$',  # "Related Work"
    ]
    
    def __init__(self, font_config: Optional[Dict[str, float]] = None):
        """Initialize with optional font threshold configuration.
        
        Args:
            font_config: Dict with 'percentile' (default 75) and 'strong_percentile' (default 90)
        """
        self.font_config = font_config or {}
        self.min_header_font_size = 9.0  # Will be recalculated per PDF
        self.strong_header_font_size = 11.0  # Will be recalculated per PDF
        self.max_header_length = 100
        self.min_paragraph_length = 50
        self.fuzzy_threshold = 0.85  # Minimum similarity for fuzzy keyword matching

    def extract_sections_from_pdf(self, pdf_path: str) -> Dict[str, str]:
        """Extract sections using PDF layout analysis with column detection."""
        try:
            doc = fitz.open(pdf_path)
            
            # First pass: analyze font sizes to determine header threshold using percentiles
            font_sizes = []
            for page in doc:
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                font_sizes.append(span["size"])
            
            if font_sizes:
                avg_font_size = np.median(font_sizes)
                # Use percentile-based thresholds (more robust than fixed offset)
                percentile = self.font_config.get('percentile', 75)
                strong_percentile = self.font_config.get('strong_percentile', 90)
                
                self.min_header_font_size = np.percentile(font_sizes, percentile)
                self.strong_header_font_size = np.percentile(font_sizes, strong_percentile)
                
                logger.info(f"Font analysis - Median: {avg_font_size:.1f}, "
                          f"Header threshold (p{percentile}): {self.min_header_font_size:.1f}, "
                          f"Strong header (p{strong_percentile}): {self.strong_header_font_size:.1f}")
            
            # Second pass: extract text with structure and column detection
            structured_content = []
            
            for page_num, page in enumerate(doc):
                # Detect columns on this page
                columns = self._detect_columns(page)
                
                if len(columns) > 1:
                    logger.info(f"Page {page_num + 1}: Detected {len(columns)} columns")
                    # Process each column separately, then merge in reading order
                    for col_idx, column_bbox in enumerate(columns):
                        col_blocks = self._get_blocks_in_bbox(page, column_bbox)
                        for block in col_blocks:
                            if block.get("type") == 0:  # Text block
                                text_content = self._extract_block_text(block)
                                if text_content:
                                    structured_content.append(text_content)
                else:
                    # Single column - process normally
                    blocks = page.get_text("dict")["blocks"]
                    blocks = sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
                    
                    for block in blocks:
                        if block.get("type") == 0:  # Text block
                            text_content = self._extract_block_text(block)
                            if text_content:
                                structured_content.append(text_content)
            
            doc.close()
            
            # Group into sections
            sections = self._group_into_sections(structured_content)
            
            # Filter out references
            if 'references' in sections:
                del sections['references']
            
            return sections
            
        except Exception as e:
            logger.error(f"Error in advanced section extraction: {e}")
            return {}
    
    def _detect_columns(self, page) -> List[Tuple[float, float, float, float]]:
        """Detect columns on a page using bounding box clustering.
        
        Returns:
            List of column bboxes as (x0, y0, x1, y1) tuples, sorted left to right
        """
        blocks = page.get_text("dict")["blocks"]
        if not blocks:
            return [(0, 0, page.rect.width, page.rect.height)]  # Full page as single column
        
        # Collect text block x-coordinates
        text_blocks = [b for b in blocks if b.get("type") == 0 and "bbox" in b]
        if len(text_blocks) < 5:  # Too few blocks to detect columns
            return [(0, 0, page.rect.width, page.rect.height)]
        
        # Group blocks by x-position (potential columns)
        x_positions = [(b["bbox"][0], b["bbox"][2]) for b in text_blocks]
        
        # Simple heuristic: if blocks have significantly different x-ranges, it's multi-column
        page_width = page.rect.width
        left_blocks = [x for x in x_positions if x[1] < page_width * 0.55]  # Left half
        right_blocks = [x for x in x_positions if x[0] > page_width * 0.45]  # Right half
        
        # If >70% of blocks are in distinct halves, assume 2 columns
        if len(left_blocks) > len(text_blocks) * 0.3 and len(right_blocks) > len(text_blocks) * 0.3:
            mid_point = page_width / 2
            return [
                (0, 0, mid_point, page.rect.height),  # Left column
                (mid_point, 0, page_width, page.rect.height)  # Right column
            ]
        
        # Single column
        return [(0, 0, page_width, page.rect.height)]
    
    def _get_blocks_in_bbox(self, page, bbox: Tuple[float, float, float, float]) -> List[Dict]:
        """Get blocks that fall within a bounding box."""
        x0, y0, x1, y1 = bbox
        blocks = page.get_text("dict")["blocks"]
        
        # Sort blocks by position (top to bottom within column)
        blocks_in_bbox = []
        for block in blocks:
            if "bbox" in block:
                bx0, by0, bx1, by1 = block["bbox"]
                # Check if block center is within bbox
                center_x = (bx0 + bx1) / 2
                center_y = (by0 + by1) / 2
                if x0 <= center_x <= x1 and y0 <= center_y <= y1:
                    blocks_in_bbox.append(block)
        
        return sorted(blocks_in_bbox, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    
    def _extract_block_text(self, block) -> Optional[Dict]:
        """Extract text and metadata from a block."""
        if "lines" not in block:
            return None
        
        text_parts = []
        max_font_size = 0
        is_bold = False
        
        for line in block["lines"]:
            line_text = ""
            for span in line["spans"]:
                line_text += span["text"]
                max_font_size = max(max_font_size, span["size"])
                if "bold" in span["font"].lower():
                    is_bold = True
            
            text_parts.append(line_text.strip())
        
        full_text = " ".join(text_parts).strip()
        
        if not full_text:
            return None
        
        # Determine if this is likely a header
        is_header = (
            max_font_size >= self.min_header_font_size and
            len(full_text) < self.max_header_length and
            (is_bold or max_font_size > self.min_header_font_size + 1)
        )
        
        return {
            'text': full_text,
            'font_size': max_font_size,
            'is_bold': is_bold,
            'is_header': is_header,
            'bbox': block['bbox']
        }
    
    def _group_into_sections(self, structured_content: List[Dict]) -> Dict[str, str]:
        """Group content into sections based on headers."""
        sections = defaultdict(list)
        current_section = 'introduction'
        headers_found = []
        
        for item in structured_content:
            text = item['text']
            text_lower = text.lower().strip()
            
            # Check if this is a section header OR matches section keywords
            matched_section = self._match_section(text_lower)
            
            if matched_section and (item['is_header'] or len(text) < 80):
                current_section = matched_section
                headers_found.append(f"{matched_section}: '{text[:50]}'")
                continue  # Don't include header in content
            
            # Skip very short fragments
            if len(text) < 20:
                continue
            
            # Add to current section
            sections[current_section].append(text)
        
        if headers_found:
            logger.info(f"Headers detected: {', '.join(set([h.split(':')[0] for h in headers_found]))}")
        else:
            logger.warning("No section headers detected - using regex fallback")
        
        # Convert lists to strings
        return {k: ' '.join(v) for k, v in sections.items() if v}
    
    def _match_section(self, text_lower: str) -> Optional[str]:
        """Match text to a section type using fuzzy matching and regex patterns."""
        from difflib import SequenceMatcher
        
        # Remove numbering (1., 2., II., etc.)
        text_clean = re.sub(r'^\d+\.?\s*', '', text_lower)
        text_clean = re.sub(r'^[ivxlcdm]+\.?\s*', '', text_clean)  # Roman numerals
        text_clean = text_clean.strip()
        
        # Try exact and partial matches first (fast path)
        for section_name, keywords in self.SECTION_KEYWORDS.items():
            for keyword in keywords:
                # Exact match or starts with keyword
                if text_clean == keyword or text_clean.startswith(keyword):
                    return section_name
                
                # Word boundary match (keyword as whole word)
                if re.search(r'\b' + re.escape(keyword) + r'\b', text_clean):
                    # Only match if keyword is near the start (within first 20 chars)
                    match_pos = text_clean.find(keyword)
                    if match_pos < 20:
                        return section_name
        
        # Try fuzzy matching for common variations (e.g., "metodology" -> "methodology")
        best_match = None
        best_score = 0.0
        
        for section_name, keywords in self.SECTION_KEYWORDS.items():
            for keyword in keywords:
                # Only fuzzy match short headers (avoid matching long paragraphs)
                if len(text_clean) < 50:
                    similarity = SequenceMatcher(None, text_clean, keyword).ratio()
                    if similarity >= self.fuzzy_threshold and similarity > best_score:
                        best_score = similarity
                        best_match = section_name
        
        if best_match:
            return best_match
        
        # Regex fallback for unmatched headers
        for pattern in self.SECTION_HEADER_PATTERNS:
            match = re.match(pattern, text_lower)
            if match:
                # Extract the header text and try to match again
                header_text = match.group(1) if match.lastindex else match.group(0)
                header_lower = header_text.lower().strip()
                
                # Try to match extracted header to known sections
                for section_name, keywords in self.SECTION_KEYWORDS.items():
                    for keyword in keywords:
                        if keyword in header_lower or header_lower in keyword:
                            return section_name
        
        return None


class EnhancedEntityExtractor:
    """Improved entity extraction with better context understanding."""
    
    def __init__(self, patterns: Dict = None, max_entities_per_type: int = 15):
        logger.info("Initializing enhanced entity extraction...")
        
        self.max_entities_per_type = max_entities_per_type
        
        # Initialize NER pipeline
        try:
            self.ner_pipeline = pipeline(
                "token-classification",
                model="allenai/scibert_scivocab_uncased",
                aggregation_strategy="simple",
                device=0 if torch.cuda.is_available() else -1,
                model_kwargs={"low_cpu_mem_usage": True}
            )
        except Exception as e:
            logger.warning(f"SciBERT NER unavailable, using fallback: {e}")
            self.ner_pipeline = None
        
        # Enhanced pattern database
        self.entity_patterns = self._build_entity_patterns(patterns)
    
    def _build_entity_patterns(self, patterns: Dict = None) -> Dict[str, List[re.Pattern]]:
        """Build comprehensive regex patterns for entities."""
        
        # If patterns provided from JSON, use them
        if patterns and 'entity_extraction' in patterns:
            entity_data = patterns['entity_extraction']
            result = {}
            for entity_type, pattern_strings in entity_data.items():
                result[entity_type] = [re.compile(p, re.I if entity_type != 'metrics' else 0) for p in pattern_strings]
            return result
        
        # Otherwise use hardcoded defaults
        return {
            'models': [
                re.compile(r'\b(GPT-?[0-9.]+[a-z]*|GPT|ChatGPT)\b', re.I),
                re.compile(r'\b(BERT|RoBERTa|ALBERT|DistilBERT|DeBERTa|SciBERT)\b'),
                re.compile(r'\b(T5|FLAN-T5|mT5)\b'),
                re.compile(r'\b(LLaMA|Llama-?[0-9]*)\b', re.I),
                re.compile(r'\b(Claude|Gemini|Mistral|Mixtral)\b'),
                re.compile(r'\b(ResNet|VGG|Inception|DenseNet|EfficientNet)[-\s]?[0-9]*', re.I),
                re.compile(r'\b(YOLO|YOLOv[0-9]+)\b', re.I),
                re.compile(r'\b(ViT|Vision Transformer|Swin Transformer)\b', re.I),
                re.compile(r'\b(CLIP|DALL-?E|Stable Diffusion)\b', re.I),
                re.compile(r'\b(Transformer|LSTM|GRU|BiLSTM)\b'),
            ],
            'datasets': [
                re.compile(r'\b(ImageNet[-\s]?[0-9]*k?)\b', re.I),
                re.compile(r'\b(COCO|MS-?COCO)\b', re.I),
                re.compile(r'\b(CIFAR-?(?:10|100))\b', re.I),
                re.compile(r'\b(MNIST|Fashion-?MNIST)\b', re.I),
                re.compile(r'\b(SQuAD[0-9.]*)\b', re.I),
                re.compile(r'\b(GLUE|SuperGLUE)\b'),
                re.compile(r'\b(WikiText[-\s]?[0-9]*)\b', re.I),
                re.compile(r'\b(Common Crawl|C4)\b', re.I),
                re.compile(r'\b(ADE20K|Cityscapes|Pascal VOC)\b', re.I),
            ],
            'metrics': [
                re.compile(r'\b(accuracy|precision|recall|F1[-\s]?score)\b', re.I),
                re.compile(r'\b(BLEU[-\s]?[0-9]*|ROUGE[-\s]?[LN0-9]*)\b', re.I),
                re.compile(r'\b(mAP|IoU|mIoU)\b'),
                re.compile(r'\b(perplexity|cross-entropy)\b', re.I),
                re.compile(r'\b(AUC|ROC|AUC-ROC)\b', re.I),
                re.compile(r'\b(METEOR|CIDEr|SPICE)\b'),
            ],
            'frameworks': [
                re.compile(r'\b(PyTorch|TensorFlow|JAX|Keras)\b', re.I),
                re.compile(r'\b(Hugging ?Face|HuggingFace)\b', re.I),
                re.compile(r'\b(scikit-learn|sklearn)\b', re.I),
            ]
        }
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """Extract entities using both patterns and NER."""
        entities = defaultdict(set)
        
        # Pattern-based extraction
        for entity_type, patterns in self.entity_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    entity = match.group(0).strip()
                    if self._validate_entity(entity, entity_type, text):
                        entities[entity_type].add(entity)
        
        # Deduplicate and limit
        final_entities = {}
        for entity_type, entity_set in entities.items():
            # Sort by frequency in text
            entity_list = list(entity_set)
            entity_counts = {e: text.count(e) for e in entity_list}
            sorted_entities = sorted(entity_list, key=lambda e: -entity_counts[e])
            final_entities[entity_type] = sorted_entities[:self.max_entities_per_type]
        
        # Ensure all keys exist
        for key in ['models', 'datasets', 'metrics', 'frameworks', 'techniques']:
            if key not in final_entities:
                final_entities[key] = []
        
        return final_entities
    
    def _validate_entity(self, entity: str, entity_type: str, context: str) -> bool:
        """Validate if entity is legitimate."""
        # Length checks
        if len(entity) < 2 or len(entity) > 50:
            return False
        
        # Must have letters
        if not any(c.isalpha() for c in entity):
            return False
        
        # Not too many special characters
        special_count = sum(1 for c in entity if c in string.punctuation)
        if special_count / len(entity) > 0.3:
            return False
        
        return True


class FlowchartGenerator:
    """Generate Mermaid flowcharts from methodology sections."""
    
    PROCESS_INDICATORS = [
        'first', 'second', 'third', 'then', 'next', 'finally', 'after',
        'step', 'stage', 'phase', 'process', 'procedure'
    ]
    
    PROCESS_VERBS = [
        'train', 'test', 'evaluate', 'collect', 'preprocess', 'extract',
        'compute', 'calculate', 'apply', 'use', 'implement', 'generate',
        'propose', 'develop', 'design', 'construct', 'build', 'optimize'
    ]

    def generate_flowchart(self, methodology_text: str) -> Optional[str]:
        """Generate flowchart from methodology section."""
        if not methodology_text or len(methodology_text) < 100:
            return None
        
        sentences = nltk.sent_tokenize(methodology_text)
        if len(sentences) < 3:
            return None
        
        # Extract process steps
        steps = self._extract_steps(sentences)
        
        if len(steps) < 2:
            return None
        
        return self._build_mermaid(steps)
    
    def _extract_steps(self, sentences: List[str]) -> List[str]:
        """Extract process steps from sentences."""
        steps = []
        seen = set()
        
        for sent in sentences[:20]:
            sent_clean = sent.strip()
            if not (30 < len(sent_clean) < 200):
                continue
            
            sent_lower = sent_clean.lower()
            
            # Check for process indicators
            has_indicator = any(ind in sent_lower for ind in self.PROCESS_INDICATORS)
            has_verb = any(verb in sent_lower for verb in self.PROCESS_VERBS)
            
            if has_indicator or has_verb:
                step = sent_clean[:120]
                if not step.endswith('.'):
                    step += '...'
                
                step_key = step[:40].lower()
                if step_key not in seen:
                    steps.append(step)
                    seen.add(step_key)
                    
                    if len(steps) >= 6:
                        break
        
        return steps
    
    def _build_mermaid(self, steps: List[str]) -> str:
        """Build Mermaid flowchart."""
        mermaid = "graph TD\n"
        mermaid += "    Start([Start])\n"
        
        for i, step in enumerate(steps):
            node_id = f"S{i+1}"
            clean_step = step.replace('"', "'").replace('\n', ' ')
            mermaid += f'    {node_id}["{clean_step}"]\n'
        
        mermaid += "    End([End])\n"
        mermaid += "    Start --> S1\n"
        
        for i in range(len(steps) - 1):
            mermaid += f"    S{i+1} --> S{i+2}\n"
        
        mermaid += f"    S{len(steps)} --> End\n"
        
        return mermaid


@dataclass
class QuantitativeResult:
    """Structured representation of experimental results."""
    metric: str
    value: str
    dataset: Optional[str] = None
    model: Optional[str] = None
    baseline_name: Optional[str] = None
    baseline_value: Optional[str] = None
    context: Optional[str] = None
    
    def to_dict(self):
        return asdict(self)


@dataclass
class ExtractedFigure:
    """Structured representation of extracted figure."""
    figure_id: str
    image_data: Optional[bytes] = None
    caption: str = ""
    page_number: int = 0
    section: str = "unknown"
    rank_score: float = 0.0
    bbox: Optional[Tuple[float, float, float, float]] = None
    
    def to_dict(self):
        data = asdict(self)
        # Convert bytes to base64 for JSON serialization
        if self.image_data:
            import base64
            data['image_data'] = base64.b64encode(self.image_data).decode('utf-8')
        # Convert bbox (fitz.Rect) to tuple if it exists
        if self.bbox is not None:
            if hasattr(self.bbox, 'x0'):  # It's a fitz.Rect object
                data['bbox'] = (self.bbox.x0, self.bbox.y0, self.bbox.x1, self.bbox.y1)
            # If it's already a tuple, it will be fine
        return data


class ResultsExtractor:
    """Extract quantitative results from tables and text using dual extraction."""
    
    # Default patterns (fallback if JSON not loaded)
    DEFAULT_METRIC_PATTERNS = [
        # Percentage metrics
        (r'(\w+(?:\s+\w+)?)\s*(?:of|:)?\s*(\d+\.?\d*)\s*%', 'percentage'),
        # "achieves X on Y" pattern
        (r'achieves?\s+(?:an?\s+)?(\w+)\s+of\s+(\d+\.?\d*)(?:\s*%)?(?:\s+on\s+([\w\-\s]+))?', 'achievement'),
        # "X: Y" pattern
        (r'(\w+(?:\s+\w+)?)\s*:\s*(\d+\.?\d*)(?:\s*%)?', 'colon'),
        # Comparison patterns
        (r'(?:outperforms?|beats?|exceeds?)\s+([\w\-\s]+)\s+by\s+(\d+\.?\d*)(?:\s*%)?', 'comparison'),
        # Improvement patterns
        (r'improves?\s+(?:over\s+)?([\w\-\s]+)\s+by\s+(\d+\.?\d*)(?:\s*%)?', 'improvement'),
    ]
    
    DEFAULT_RESULT_KEYWORDS = [
        'accuracy', 'precision', 'recall', 'f1', 'score', 'bleu', 'rouge',
        'perplexity', 'map', 'iou', 'auc', 'loss', 'error', 'rate',
        'performance', 'result', 'metric'
    ]
    
    def __init__(self, patterns: Dict = None, max_results: int = 50):
        self.results = []
        self.max_results = max_results
        
        # Load patterns from config or use defaults
        if patterns and 'results_extraction' in patterns:
            pattern_data = patterns['results_extraction'].get('metric_patterns', [])
            self.METRIC_PATTERNS = [(p['pattern'], p['type']) for p in pattern_data]
            self.RESULT_KEYWORDS = patterns['results_extraction'].get('result_keywords', self.DEFAULT_RESULT_KEYWORDS)
        else:
            self.METRIC_PATTERNS = self.DEFAULT_METRIC_PATTERNS
            self.RESULT_KEYWORDS = self.DEFAULT_RESULT_KEYWORDS
    
    def extract_from_pdf(self, pdf_path: str, sections: Dict[str, str]) -> List[QuantitativeResult]:
        """Extract results using both table and text methods."""
        results = []
        
        # Extract from tables using both PyMuPDF and pdfplumber
        logger.info("📊 Extracting results from tables...")
        table_results = self._extract_from_tables_dual(pdf_path)
        results.extend(table_results)
        
        # Extract from inline text in Results/Experiments sections
        logger.info("📊 Extracting results from text...")
        for section_name in ['results', 'experiments', 'discussion']:
            if section_name in sections:
                text_results = self._extract_from_text(sections[section_name], section_name)
                results.extend(text_results)
        
        # Deduplicate and rank
        results = self._deduplicate_results(results)
        logger.info(f"✅ Extracted {len(results)} quantitative results")
        
        return results
    
    def _extract_from_tables_dual(self, pdf_path: str) -> List[QuantitativeResult]:
        """Extract tables using both PyMuPDF and pdfplumber for robustness."""
        results = []
        
        # Method 1: pdfplumber (better table structure detection)
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    for table in tables:
                        if table:
                            table_results = self._parse_table(table, page_num, 'pdfplumber')
                            results.extend(table_results)
        except Exception as e:
            logger.warning(f"pdfplumber table extraction failed: {e}")
        
        # Method 2: PyMuPDF (fallback and cross-validation)
        try:
            doc = fitz.open(pdf_path)
            for page_num, page in enumerate(doc):
                # Look for table-like structures using text blocks
                blocks = page.get_text("dict")["blocks"]
                table_blocks = self._find_table_blocks_pymupdf(blocks)
                for table_data in table_blocks:
                    table_results = self._parse_table(table_data, page_num, 'pymupdf')
                    results.extend(table_results)
            doc.close()
        except Exception as e:
            logger.warning(f"PyMuPDF table extraction failed: {e}")
        
        return results
    
    def _find_table_blocks_pymupdf(self, blocks: List) -> List[List[List[str]]]:
        """Find table-like structures in PyMuPDF blocks."""
        # Simple heuristic: look for aligned text blocks with numbers
        # This is a fallback - pdfplumber is better for actual tables
        tables = []
        
        # Group blocks by y-coordinate (rows)
        rows = defaultdict(list)
        for block in blocks:
            if block.get("type") == 0:  # Text block
                text = ""
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text += span["text"] + " "
                if text.strip():
                    y_coord = round(block["bbox"][1] / 10) * 10  # Group by approximate y
                    rows[y_coord].append((block["bbox"][0], text.strip()))
        
        # Convert to table format if we have multiple aligned rows with numbers
        for y_coord, row_blocks in rows.items():
            if len(row_blocks) >= 2:
                # Sort by x-coordinate
                row_blocks.sort(key=lambda x: x[0])
                row = [text for _, text in row_blocks]
                # Check if row has numbers (likely a data row)
                if any(re.search(r'\d+\.?\d*', cell) for cell in row):
                    tables.append([row])
        
        return tables
    
    def _parse_table(self, table: List[List[str]], page_num: int, method: str) -> List[QuantitativeResult]:
        """Parse a table and extract quantitative results."""
        results = []
        
        if not table or len(table) < 2:
            return results
        
        # Try to identify header row
        header = table[0] if table else []
        data_rows = table[1:] if len(table) > 1 else []
        
        # Look for metric columns
        metric_cols = []
        for idx, cell in enumerate(header):
            if cell and any(keyword in str(cell).lower() for keyword in self.RESULT_KEYWORDS):
                metric_cols.append((idx, str(cell)))
        
        # Extract from data rows
        for row in data_rows:
            if not row:
                continue
            
            # Look for model/dataset name in first column
            model_or_dataset = str(row[0]) if row else ""
            
            for col_idx, metric_name in metric_cols:
                if col_idx < len(row) and row[col_idx]:
                    value = str(row[col_idx]).strip()
                    # Check if value is numeric
                    if re.search(r'\d+\.?\d*', value):
                        results.append(QuantitativeResult(
                            metric=metric_name,
                            value=value,
                            model=model_or_dataset if model_or_dataset else None,
                            context=f"Table on page {page_num + 1} (extracted via {method})"
                        ))
        
        return results
    
    def _extract_from_text(self, text: str, section_name: str) -> List[QuantitativeResult]:
        """Extract results from inline text using regex patterns."""
        results = []
        sentences = nltk.sent_tokenize(text)
        
        for sent in sentences:
            # Skip very short sentences
            if len(sent) < 20:
                continue
            
            for pattern, pattern_type in self.METRIC_PATTERNS:
                matches = re.finditer(pattern, sent, re.IGNORECASE)
                for match in matches:
                    if pattern_type == 'percentage':
                        metric, value = match.groups()
                        results.append(QuantitativeResult(
                            metric=metric.strip(),
                            value=f"{value}%",
                            context=sent[:200]
                        ))
                    
                    elif pattern_type == 'achievement':
                        metric, value, dataset = match.groups()
                        results.append(QuantitativeResult(
                            metric=metric.strip(),
                            value=value + ('%' if '%' in match.group(0) else ''),
                            dataset=dataset.strip() if dataset else None,
                            context=sent[:200]
                        ))
                    
                    elif pattern_type == 'colon':
                        metric, value = match.groups()
                        # Only accept if metric is a known metric keyword
                        if any(kw in metric.lower() for kw in self.RESULT_KEYWORDS):
                            results.append(QuantitativeResult(
                                metric=metric.strip(),
                                value=value + ('%' if '%' in match.group(0) else ''),
                                context=sent[:200]
                            ))
                    
                    elif pattern_type in ['comparison', 'improvement']:
                        baseline, improvement = match.groups()
                        results.append(QuantitativeResult(
                            metric='improvement',
                            value=improvement + ('%' if '%' in match.group(0) else ''),
                            baseline_name=baseline.strip(),
                            context=sent[:200]
                        ))
        
        return results
    
    def _deduplicate_results(self, results: List[QuantitativeResult]) -> List[QuantitativeResult]:
        """Remove duplicate results."""
        seen = set()
        unique = []
        
        for result in results:
            # Create a key based on metric + value
            key = f"{result.metric.lower()}_{result.value}"
            if key not in seen:
                seen.add(key)
                unique.append(result)
                
                # Respect max_results limit
                if len(unique) >= self.max_results:
                    break
        
        return unique


class FigureExtractor:
    """Extract and rank figures from PDFs."""
    
    IMPORTANT_SECTIONS = ['results', 'experiments', 'methodology', 'method', 'approach']
    IMPORTANT_KEYWORDS = [
        'architecture', 'model', 'framework', 'pipeline', 'system',
        'performance', 'comparison', 'accuracy', 'result', 'graph',
        'plot', 'chart', 'diagram', 'overview'
    ]
    
    def __init__(self, max_figures: int = 10, enable_ocr: bool = True):
        self.max_figures = max_figures
        self.enable_ocr = enable_ocr
        self.ocr_available = pytesseract is not None and Image is not None and enable_ocr
        if not self.ocr_available and enable_ocr:
            logger.warning("OCR unavailable - figure captions will not be extracted")
    
    def extract_figures(self, pdf_path: str, sections: Dict[str, str]) -> List[ExtractedFigure]:
        """Extract figures with ranking."""
        figures = []
        
        logger.info("🖼️  Extracting figures from PDF...")
        
        try:
            doc = fitz.open(pdf_path)
            
            for page_num, page in enumerate(doc):
                # Extract images
                image_list = page.get_images(full=True)
                
                for img_idx, img_info in enumerate(image_list):
                    xref = img_info[0]
                    
                    # Extract image
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue
                    
                    image_bytes = base_image["image"]
                    
                    # Filter by size
                    try:
                        if Image:
                            img = Image.open(BytesIO(image_bytes))
                            width, height = img.size
                            
                            # Skip small images (logos, bullets, etc.)
                            if width < 50 or height < 50:
                                continue
                            
                            # Skip very wide/tall images (likely decorations)
                            aspect_ratio = max(width, height) / min(width, height)
                            if aspect_ratio > 10:
                                continue
                    except Exception as e:
                        logger.debug(f"Image size check failed: {e}")
                        continue
                    
                    # Get image position for caption extraction
                    img_rects = page.get_image_rects(xref)
                    bbox = img_rects[0] if img_rects else None
                    
                    # Extract caption
                    caption = self._extract_caption(page, bbox, page_num)
                    
                    # Determine section
                    section = self._determine_section(page_num, doc, sections)
                    
                    # Create figure
                    figure = ExtractedFigure(
                        figure_id=f"fig_{page_num}_{img_idx}",
                        image_data=image_bytes,
                        caption=caption,
                        page_number=page_num + 1,
                        section=section,
                        bbox=bbox
                    )
                    
                    # Calculate rank score
                    figure.rank_score = self._calculate_rank(figure, sections)
                    
                    figures.append(figure)
            
            doc.close()
            
        except Exception as e:
            logger.error(f"Figure extraction failed: {e}")
        
        # Sort by rank
        figures.sort(key=lambda f: f.rank_score, reverse=True)
        
        logger.info(f"✅ Extracted {len(figures)} figures (top {self.max_figures})")
        return figures[:self.max_figures]
    
    def _extract_caption(self, page, bbox, page_num: int) -> str:
        """Extract caption text near image."""
        if not bbox:
            return ""
        
        # Look for text below the image
        caption_area = fitz.Rect(
            bbox.x0,
            bbox.y1,
            bbox.x1,
            min(bbox.y1 + 100, page.rect.height)
        )
        
        caption_text = page.get_text("text", clip=caption_area).strip()
        
        # Look for "Figure X:" pattern
        fig_match = re.search(r'Figure\s+\d+[.:]\s*(.*?)(?:\n|$)', caption_text, re.IGNORECASE)
        if fig_match:
            return fig_match.group(1).strip()[:200]
        
        # Use OCR if available and no text found
        if not caption_text and self.ocr_available:
            try:
                pix = page.get_pixmap(clip=caption_area)
                img = Image.open(BytesIO(pix.tobytes()))
                caption_text = pytesseract.image_to_string(img).strip()
            except Exception:
                pass
        
        return caption_text[:200]
    
    def _determine_section(self, page_num: int, doc, sections: Dict[str, str]) -> str:
        """Determine which section a page belongs to."""
        # Simple heuristic: check page position relative to total pages
        total_pages = len(doc)
        
        if page_num < total_pages * 0.2:
            return "introduction"
        elif page_num < total_pages * 0.5:
            return "methodology"
        elif page_num < total_pages * 0.8:
            return "results"
        else:
            return "conclusion"
    
    def _calculate_rank(self, figure: ExtractedFigure, sections: Dict[str, str]) -> float:
        """Calculate importance rank for figure."""
        score = 0.0
        
        # Section importance
        if figure.section in self.IMPORTANT_SECTIONS:
            score += 5.0
        
        # Caption keywords
        caption_lower = figure.caption.lower()
        for keyword in self.IMPORTANT_KEYWORDS:
            if keyword in caption_lower:
                score += 2.0
        
        # Architecture/model diagrams are important
        if any(word in caption_lower for word in ['architecture', 'model', 'framework', 'pipeline']):
            score += 10.0
        
        # Results/performance graphs are important
        if any(word in caption_lower for word in ['performance', 'comparison', 'accuracy', 'result']):
            score += 8.0
        
        # Length of caption (more detail = more important)
        if len(figure.caption) > 50:
            score += 1.0
        
        return score


class ImprovedPDFExtractor:
    """Improved PDF text extraction with column handling."""
    
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text with improved handling of layouts."""
        try:
            doc = fitz.open(pdf_path)
            text_parts = []
            
            logger.info(f"📄 Processing {len(doc)} pages from {Path(pdf_path).name}")
            
            for page_num, page in enumerate(doc):
                # Use blocks for better layout handling
                blocks = page.get_text("blocks")
                
                # Sort blocks by position (top to bottom, handling columns)
                blocks = sorted(blocks, key=lambda b: (b[1], b[0]))  # y, then x
                
                page_text = ""
                for block in blocks:
                    if len(block) >= 5:
                        block_text = block[4].strip()
                        if len(block_text) > 20:
                            page_text += block_text + "\n"
                
                if page_text:
                    text_parts.append(page_text)
                
                if page_num % 5 == 0:
                    logger.info(f"  ✓ Processed page {page_num + 1}/{len(doc)}")
            
            doc.close()
            
            full_text = "\n".join(text_parts)
            logger.info(f"✅ Extracted {len(full_text):,} characters")
            
            return full_text
            
        except Exception as e:
            logger.error(f"❌ Error extracting from {pdf_path}: {e}")
            return ""


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="ArXiv research paper summarizer using parallel multi-agent system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Summarize 5 ML papers:
  python main.py --query "cat:cs.LG" --max-results 5
  
  # Use lightweight mode:
  python main.py --lightweight --max-results 3
  
  # Use custom patterns file:
  python main.py --patterns custom_patterns.json
  
  # Use custom config file:
  python main.py --config config.yaml
        """
    )
    parser.add_argument("--query", default="cat:cs.LG", 
                       help="arXiv query (e.g., 'cat:cs.CV', 'ti:transformer', 'all:neural networks')")
    parser.add_argument("--max-results", type=int, default=5, 
                       help="maximum number of papers to fetch and summarize")
    parser.add_argument("--save-dir", default="arxiv_papers", 
                       help="directory to save downloaded PDFs")
    parser.add_argument("--lightweight", action="store_true",
                       help="reduce resource usage: fewer figures (5), entities (10), results (30), no OCR")
    parser.add_argument("--patterns", default="patterns.json",
                       help="path to patterns JSON file (default: patterns.json)")
    parser.add_argument("--max-figures", type=int, default=None,
                       help="maximum figures to extract (default: 10, lightweight: 5)")
    parser.add_argument("--max-entities", type=int, default=None,
                       help="maximum entities per type (default: 15, lightweight: 10)")
    parser.add_argument("--max-quant-results", type=int, default=None,
                       help="maximum quantitative results (default: 50, lightweight: 30)")
    parser.add_argument("--no-ocr", action="store_true",
                       help="disable OCR for figure captions (faster, less accurate)")
    parser.add_argument("--config", default=None,
                       help="path to YAML config file (optional, overrides defaults)")
    args = parser.parse_args(argv)
    
    # Load config file if specified
    config = load_config(args.config) if args.config else {}
    
    # Apply lightweight mode defaults (CLI args override config)
    if args.lightweight:
        max_figures = args.max_figures if args.max_figures is not None else config.get('max_figures', 5)
        max_entities = args.max_entities if args.max_entities is not None else config.get('max_entities', 10)
        max_results = args.max_quant_results if args.max_quant_results is not None else config.get('max_results', 30)
        enable_ocr = False
        logger.info("🪶 Lightweight mode enabled (fewer resources)")
    else:
        max_figures = args.max_figures if args.max_figures is not None else config.get('max_figures', 10)
        max_entities = args.max_entities if args.max_entities is not None else config.get('max_entities', 15)
        max_results = args.max_quant_results if args.max_quant_results is not None else config.get('max_results', 50)
        enable_ocr = not args.no_ocr and config.get('enable_ocr', True)
    
    # Load patterns (can be specified in config)
    patterns_file = config.get('patterns_file', args.patterns)
    patterns = load_patterns(patterns_file)

    # Fetch papers
    fetcher = ArxivDatasetFetcher(
        query=args.query,
        max_results=args.max_results,
        save_dir=args.save_dir
    )
    papers = fetcher.fetch_papers()
    pdf_paths = fetcher.download_pdfs(papers)

    # Create summaries folder
    summaries_folder = Path("summaries_final")
    summaries_folder.mkdir(parents=True, exist_ok=True)

    # Use parallel multi-agent system
    logger.info("\n🤖 Using parallel multi-agent system")
    
    from core.agent_integration import run_agent_mode
    
    # Process each paper with agents
    all_summaries = []
    for pdf_path, paper in zip(pdf_paths, papers):
        logger.info(f"\n📄 Processing: {paper['title']}")
        try:
            result = run_agent_mode(pdf_path, config, patterns)
            
            # Update with arxiv metadata
            result['arxiv_id'] = paper['arxiv_id']
            result['title'] = paper['title']
            result['authors'] = paper['authors']
            result['published'] = paper['published']
            result['updated'] = paper.get('updated', paper['published'])
            
            all_summaries.append(result)
            
            # Save individual summary
            summary_file = summaries_folder / f"summary_{result['arxiv_id']}.json"
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✅ Saved: {summary_file}")
            logger.info(f"   Time: {result['agent_metadata']['total_time_ms']:.0f}ms")
            logger.info(f"   Speedup: {result['agent_metadata']['speedup']:.2f}x")
            logger.info(f"   LLM: {result['agent_metadata']['llm_backend']}")
            
        except Exception as e:
            logger.error(f"❌ Error processing {paper['title']}: {e}")
            import traceback
            traceback.print_exc()
    
    # Create combined dataset
    dataset_file = summaries_folder / "arxiv_summaries_dataset.json"
    with open(dataset_file, 'w', encoding='utf-8') as f:
        json.dump(all_summaries, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\n✅ Processing complete!")
    logger.info(f"   Papers processed: {len(all_summaries)}")
    logger.info(f"   Dataset saved: {dataset_file}")
    
    return 0


if __name__ == "__main__":
    main()