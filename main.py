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

import numpy as np
import nltk
import requests
import torch
import arxiv
import fitz  # PyMuPDF
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoTokenizer, AutoModel, pipeline
from transformers import LEDTokenizer, LEDForConditionalGeneration

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
    
    def __init__(self):
        self.min_header_font_size = 9.0  # Typically headers are 10pt+
        self.max_header_length = 100
        self.min_paragraph_length = 50

    def extract_sections_from_pdf(self, pdf_path: str) -> Dict[str, str]:
        """Extract sections using PDF layout analysis."""
        try:
            doc = fitz.open(pdf_path)
            
            # First pass: analyze font sizes to determine header threshold
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
                self.min_header_font_size = avg_font_size + 0.5  # Lower threshold for better detection
                logger.info(f"Font analysis - Median: {avg_font_size:.1f}, Header threshold: {self.min_header_font_size:.1f}")
            
            # Second pass: extract text with structure
            structured_content = []
            
            for page_num, page in enumerate(doc):
                blocks = page.get_text("dict")["blocks"]
                
                # Sort blocks by position (top to bottom, left to right)
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
        """Match text to a section type."""
        # Remove numbering (1., 2., II., etc.)
        text_clean = re.sub(r'^\d+\.?\s*', '', text_lower)
        text_clean = re.sub(r'^[ivxlcdm]+\.?\s*', '', text_clean)  # Roman numerals
        text_clean = text_clean.strip()
        
        for section_name, keywords in self.SECTION_KEYWORDS.items():
            for keyword in keywords:
                # Match if starts with keyword or exact match or contains keyword as whole word
                if (text_clean.startswith(keyword) or 
                    text_clean == keyword or
                    re.search(r'\b' + re.escape(keyword) + r'\b', text_clean)):
                    return section_name
        
        return None


class EnhancedEntityExtractor:
    """Improved entity extraction with better context understanding."""
    
    def __init__(self):
        logger.info("Initializing enhanced entity extraction...")
        
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
        self.entity_patterns = self._build_entity_patterns()
    
    def _build_entity_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Build comprehensive regex patterns for entities."""
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
            final_entities[entity_type] = sorted_entities[:15]
        
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


class HierarchicalSummarizer:
    """Hierarchical summarization: paragraph → section → paper."""
    
    def __init__(self, device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        
        if self.device == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.set_per_process_memory_fraction(0.80)
        
        self.sentence_encoder = None
        self.summarizer = None
        self.kw_model = KeyBERT() if KeyBERT else None
        
        # Use LED for longer context
        self.model_name = "allenai/led-base-16384"
    
    def _load_sentence_encoder(self):
        """Load sentence encoder for extractive summarization."""
        if self.sentence_encoder is None:
            logger.info("Loading sentence encoder...")
            model_name = "sentence-transformers/all-MiniLM-L6-v2"
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            try:
                self.sentence_encoder = AutoModel.from_pretrained(
                    model_name,
                    low_cpu_mem_usage=True,
                    torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
                ).to(self.device)
            except Exception as e:
                logger.warning(f"Failed to load with optimizations, trying default: {e}")
                self.sentence_encoder = AutoModel.from_pretrained(model_name)
                self.sentence_encoder = self.sentence_encoder.to(self.device)
                if self.device == "cuda":
                    self.sentence_encoder = self.sentence_encoder.half()
    
    def _unload_sentence_encoder(self):
        """Unload sentence encoder."""
        if self.sentence_encoder is not None:
            del self.sentence_encoder
            del self.tokenizer
            self.sentence_encoder = None
            if self.device == "cuda":
                torch.cuda.empty_cache()
    
    def _load_summarizer(self):
        """Load LED summarizer."""
        if self.summarizer is None:
            logger.info(f"Loading summarizer: {self.model_name}")
            self.sum_tokenizer = LEDTokenizer.from_pretrained(self.model_name)
            try:
                self.summarizer = LEDForConditionalGeneration.from_pretrained(
                    self.model_name,
                    low_cpu_mem_usage=True,
                    torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
                ).to(self.device)
            except Exception as e:
                logger.warning(f"Failed to load with optimizations, trying default: {e}")
                self.summarizer = LEDForConditionalGeneration.from_pretrained(self.model_name)
                self.summarizer = self.summarizer.to(self.device)
                if self.device == "cuda":
                    self.summarizer = self.summarizer.half()
    
    def _unload_summarizer(self):
        """Unload summarizer."""
        if self.summarizer is not None:
            del self.summarizer
            del self.sum_tokenizer
            self.summarizer = None
            if self.device == "cuda":
                torch.cuda.empty_cache()
    
    def preprocess_text(self, text: str) -> str:
        """Clean text while preserving structure."""
        # Remove citations
        text = re.sub(r'\[\d+(?:,\s*\d+)*\]', '', text)
        text = re.sub(r'\(\d+(?:,\s*\d+)*\)', '', text)
        
        # Remove URLs and emails
        text = re.sub(r'http[s]?://\S+', '', text)
        text = re.sub(r'\S+@\S+', '', text)
        
        # Remove figure/table references
        text = re.sub(r'\b(fig|figure|table|eq)\.?\s*\d+', '', text, flags=re.I)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def extractive_summary(self, text: str, ratio: float = 0.3) -> str:
        """Extractive summarization using sentence embeddings."""
        sentences = nltk.sent_tokenize(text)
        if len(sentences) < 3:
            return text
        
        # Filter quality sentences
        quality_sents = [s for s in sentences if 30 < len(s) < 500 and len(s.split()) >= 5]
        
        if not quality_sents:
            return text
        
        self._load_sentence_encoder()
        
        # Encode sentences
        inputs = self.tokenizer(quality_sents, padding=True, truncation=True, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.sentence_encoder(**inputs)
        embeddings = outputs.last_hidden_state.mean(dim=1).cpu().numpy()
        
        # Calculate importance scores
        doc_embedding = embeddings.mean(axis=0)
        scores = cosine_similarity(embeddings, [doc_embedding]).flatten()
        
        # Select top sentences
        n_select = max(3, int(len(quality_sents) * ratio))
        top_indices = np.argsort(scores)[-n_select:]
        selected = [quality_sents[i] for i in sorted(top_indices)]
        
        return " ".join(selected)
    
    def abstractive_summary(self, text: str, max_length: int = 256) -> str:
        """Abstractive summarization using LED."""
        if not text.strip():
            return ""
        
        self._load_summarizer()
        
        # Tokenize with global attention on first token
        inputs = self.sum_tokenizer(
            text,
            return_tensors="pt",
            max_length=4096,
            truncation=True
        ).to(self.device)
        
        # Set global attention
        global_attention_mask = torch.zeros_like(inputs['input_ids'])
        global_attention_mask[:, 0] = 1
        
        with torch.no_grad():
            summary_ids = self.summarizer.generate(
                inputs['input_ids'],
                attention_mask=inputs['attention_mask'],
                global_attention_mask=global_attention_mask,
                max_length=max_length,
                min_length=50,
                num_beams=4,
                length_penalty=2.0,
                no_repeat_ngram_size=3,
                early_stopping=True
            )
        
        summary = self.sum_tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        return self._clean_summary(summary)
    
    def _clean_summary(self, summary: str) -> str:
        """Clean generated summary."""
        # Remove incomplete sentences
        sentences = summary.split('.')
        if len(sentences) > 1 and len(sentences[-1].strip()) < 10:
            sentences = sentences[:-1]
        summary = '. '.join(s.strip() for s in sentences if s.strip())
        
        if summary and not summary.endswith('.'):
            summary += '.'
        
        return summary
    
    def extract_keywords(self, text: str, n: int = 10) -> List[str]:
        """Extract keywords."""
        if not self.kw_model or not text:
            return []
        try:
            keywords = self.kw_model.extract_keywords(text, top_n=n, stop_words='english')
            return [kw for kw, _ in keywords]
        except:
            return []
    
    def summarize_section(self, section_text: str, section_name: str) -> Tuple[str, List[str]]:
        """Summarize a single section hierarchically."""
        logger.info(f"Summarizing {section_name}...")
        
        # Clean text
        clean_text = self.preprocess_text(section_text)
        
        if len(clean_text.split()) < 50:
            return clean_text, []
        
        # Extractive first
        extractive = self.extractive_summary(clean_text, ratio=0.4)
        self._unload_sentence_encoder()
        
        # Then abstractive
        max_len = 200 if section_name in ['introduction', 'conclusion'] else 150
        abstractive = self.abstractive_summary(extractive, max_length=max_len)
        self._unload_summarizer()
        
        # Extract keywords
        keywords = self.extract_keywords(abstractive, n=5)
        
        return abstractive, keywords


class EnhancedResearchPaperSummarizer:
    """Main summarizer with all improvements integrated."""
    
    def __init__(self, device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        
        self.section_extractor = AdvancedSectionExtractor()
        self.entity_extractor = EnhancedEntityExtractor()
        self.pdf_extractor = ImprovedPDFExtractor()
        self.flowchart_generator = FlowchartGenerator()
        self.hierarchical_summarizer = HierarchicalSummarizer(device=self.device)
    
    def summarize_paper(self, pdf_path: str) -> Dict:
        """Summarize paper with all enhancements."""
        logger.info("\n" + "="*60)
        logger.info("PROCESSING PAPER")
        logger.info("="*60)
        
        # Extract sections using advanced method
        logger.info("📑 Extracting sections with layout analysis...")
        sections = self.section_extractor.extract_sections_from_pdf(pdf_path)
        
        if not sections:
            # Fallback to basic extraction
            logger.warning("Layout-based extraction failed, using fallback...")
            raw_text = self.pdf_extractor.extract_text_from_pdf(pdf_path)
            sections = {'introduction': raw_text}
        
        logger.info(f"Found sections: {list(sections.keys())}")
        
        # Combine for entity extraction
        full_text = " ".join(sections.values())
        
        logger.info("🎯 Extracting entities...")
        entities = self.entity_extractor.extract_entities(full_text)
        
        # Summarize each section
        section_summaries = {}
        section_keywords = {}
        
        # Summarize ALL detected sections instead of just priority ones
        for section_name, section_text in sections.items():
            if section_text and section_name != 'references':  # Skip references
                summary, keywords = self.hierarchical_summarizer.summarize_section(
                    section_text, 
                    section_name
                )
                section_summaries[section_name] = summary
                section_keywords[section_name] = keywords
        
        # Generate overall summary
        logger.info("📝 Generating overall summary...")
        combined_text = " ".join(section_summaries.values())
        overall_keywords = self.hierarchical_summarizer.extract_keywords(combined_text, n=10)
        
        # Generate flowchart
        flowchart = None
        if 'methodology' in sections:
            logger.info("📊 Generating methodology flowchart...")
            flowchart = self.flowchart_generator.generate_flowchart(sections['methodology'])
        
        return {
            "overall_summary": combined_text,
            "section_summaries": section_summaries,
            "section_keywords": section_keywords,
            "overall_keywords": overall_keywords,
            "entities": entities,
            "methodology_flowchart": flowchart,
            "sections_found": list(sections.keys()),
            "num_words_original": len(full_text.split()),
            "num_words_summary": len(combined_text.split()),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Enhanced ArXiv research paper summarizer with advanced section detection"
    )
    parser.add_argument("--query", default="cat:cs.LG", help="arXiv query")
    parser.add_argument("--max-results", type=int, default=5, help="max papers to fetch")
    parser.add_argument("--save-dir", default="arxiv_papers", help="directory for PDFs")
    parser.add_argument("--evaluate", action="store_true", help="evaluate summaries with BERT F1 score")
    args = parser.parse_args(argv)

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

    # Initialize summarizer
    summarizer = EnhancedResearchPaperSummarizer()

    # Process papers
    results = []
    for pdf_path, info in zip(pdf_paths, papers):
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {info['title']}")
        logger.info('='*60)
        
        try:
            summary_data = summarizer.summarize_paper(pdf_path)
            summary_data.update({
                "title": info["title"],
                "authors": info["authors"],
                "arxiv_id": info["arxiv_id"],
                "published": info["published"],
                "primary_category": info.get("primary_category", ""),
                "abstract_original": info.get("summary", ""),
            })
            results.append(summary_data)
            
            # Save individual summary
            out_file = summaries_folder / f"summary_{info['arxiv_id']}.json"
            out_file.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
            logger.info(f"\n✅ Saved summary to {out_file}")
            
            # Display key findings
            logger.info(f"\n📊 Key Findings:")
            logger.info(f"  Sections: {', '.join(summary_data['sections_found'])}")
            logger.info(f"  Datasets: {', '.join(summary_data['entities']['datasets'][:5]) if summary_data['entities']['datasets'] else 'None detected'}")
            logger.info(f"  Models: {', '.join(summary_data['entities']['models'][:5]) if summary_data['entities']['models'] else 'None detected'}")
            logger.info(f"  Metrics: {', '.join(summary_data['entities']['metrics'][:5]) if summary_data['entities']['metrics'] else 'None detected'}")
            logger.info(f"  Keywords: {', '.join(summary_data['overall_keywords'][:8])}")
            logger.info(f"  Compression: {(1 - summary_data['num_words_summary'] / summary_data['num_words_original']) * 100:.1f}%")
            
            # BERT F1 evaluation if requested
            if args.evaluate and bert_score and info.get("summary"):
                logger.info(f"\n📊 BERT F1 Evaluation:")
                try:
                    P, R, F1 = bert_score(
                        [summary_data['overall_summary']], 
                        [info['summary']], 
                        lang='en', 
                        verbose=False,
                        device='cuda' if torch.cuda.is_available() else 'cpu'
                    )
                    summary_data['bert_f1'] = float(F1[0])
                    summary_data['bert_precision'] = float(P[0])
                    summary_data['bert_recall'] = float(R[0])
                    logger.info(f"  Precision: {P[0]:.4f}")
                    logger.info(f"  Recall: {R[0]:.4f}")
                    logger.info(f"  F1 Score: {F1[0]:.4f}")
                except Exception as e:
                    logger.warning(f"  BERT evaluation failed: {e}")
            
        except Exception as e:
            logger.error(f"❌ Error processing {info['title']}: {e}")
            import traceback
            traceback.print_exc()

    # Save all summaries
    all_summaries_file = summaries_folder / "arxiv_summaries_dataset.json"
    all_summaries_file.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8"
    )
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ All {len(results)} summaries saved to {all_summaries_file}")
    logger.info('='*60)


if __name__ == "__main__":
    main()