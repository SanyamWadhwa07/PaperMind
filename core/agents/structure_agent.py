"""StructureAgent - Analyzes PDF structure and extracts sections.

Extraction priority:
  1. MinerU (magic-pdf) — best quality, also extracts figure PNGs
  2. pymupdf4llm — fast, handles clean native PDFs
  3. AdvancedSectionExtractor (backend.main) — font-heuristic fallback

Pre-extracted figures are passed downstream via 'pre_extracted_figures'
in the returned result so FigureAgent can skip redundant extraction.
"""

import asyncio
import sys
import structlog
from pathlib import Path
from typing import Dict, List, Any, Optional

sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState
from core.pipeline.pdf_extractor import extract_pdf, ExtractionResult
from backend.main import AdvancedSectionExtractor

logger = structlog.get_logger(__name__)


class StructureAgent(BaseAgent):
    """
    Agent responsible for PDF structure analysis.
    
    Capabilities:
    - Extract sections using font-based detection with learned thresholds
    - Learn common section patterns and font configurations by domain
    - Answer queries about section locations
    - Track section dependencies
    """
    
    def __init__(self, patterns: Optional[Dict] = None, font_config: Optional[Dict] = None):
        super().__init__(name="StructureAgent", patterns=patterns)
        self.font_config = font_config or {'percentile': 75, 'strong_percentile': 90}
        self.section_extractor = AdvancedSectionExtractor(font_config=self.font_config)
        self.current_sections: Dict[str, str] = {}
        self.section_locations: Dict[str, List[int]] = {}
        self.domain_font_cache: Dict[str, Dict[str, float]] = {}
        self._pre_extracted_figures: list = []  # FigureInfo list from last extraction
    
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract sections from PDF.
        
        Args:
            input_data: {
                'pdf_path': str - Path to PDF file
                'domain': str - Optional paper domain (cv, nlp, ml)
            }
        
        Returns:
            {
                'extractions': List of section names found,
                'confidence_scores': Dict mapping section -> confidence,
                'sections': Dict mapping section -> text content,
                'metadata': {
                    'section_count': int,
                    'total_words': int,
                    'domain_match': str
                }
            }
        """
        pdf_path = input_data.get('pdf_path')
        domain = input_data.get('domain', 'general')
        
        if not pdf_path:
            raise ValueError("pdf_path required")

        # Load domain-specific font configuration from experience if available
        font_config = await self._get_domain_font_config(domain)
        if font_config:
            self.section_extractor = AdvancedSectionExtractor(font_config=font_config)

        # ── New layered extractor: MinerU → pymupdf4llm → fitz ─────────────
        # MinerU tier is opt-in (PAPERMIND_ENABLE_MINERU) — see extract_pdf's
        # docstring; leave prefer_mineru unset so that governs it.
        # Off the event loop: extract_pdf is fully synchronous and its table
        # step shells out to a subprocess with a 120s timeout, retried once —
        # so a slow paper could stall every other coroutine for four minutes.
        extraction: ExtractionResult = await asyncio.to_thread(extract_pdf, pdf_path)
        sections = extraction.sections
        pre_extracted_figures = extraction.figures  # List[FigureInfo]

        # ── Legacy fallback if new extractor found too few sections ─────────
        if len(sections) < 3:
            logger.info(
                "new_extractor_insufficient_sections",
                found=len(sections),
                backend=extraction.backend,
                fallback="AdvancedSectionExtractor",
            )
            sections = await asyncio.to_thread(
                self.section_extractor.extract_sections_from_pdf, pdf_path)
            pre_extracted_figures = []

        self.current_sections = sections
        self._pre_extracted_figures = pre_extracted_figures
        
        # Query experience for expected structure
        expected_template = await self.query_experience(
            'section_template',
            domain=domain
        )
        
        # Calculate confidence scores based on:
        # 1. Section completeness (has expected sections)
        # 2. Match with learned templates
        confidence_scores = {}
        expected_sections = ['introduction', 'methodology', 'results', 'conclusion']
        
        if expected_template:
            expected_sections = expected_template.get('section_sequence', expected_sections)
        
        for section_name in sections.keys():
            # Base confidence from extraction
            confidence = 0.8 if section_name in expected_sections else 0.6
            
            # Boost if section has substantial content
            word_count = len(sections[section_name].split())
            if word_count > 100:
                confidence = min(confidence + 0.1, 1.0)
            
            confidence_scores[section_name] = confidence
        
        # Learn from this paper's structure
        if len(sections) >= 4:  # Only learn from substantial papers
            await self._update_section_template(domain, list(sections.keys()))
            # Also learn font configuration that worked well
            await self._store_font_config(domain, self.section_extractor.min_header_font_size,
                                         self.section_extractor.strong_header_font_size)
        
        total_words = sum(len(text.split()) for text in sections.values())
        
        # Determine domain match confidence
        domain_match = self._infer_domain(sections)
        
        return {
            'extractions': list(sections.keys()),
            'confidence_scores': confidence_scores,
            'sections': sections,
            'pre_extracted_figures': self._pre_extracted_figures,
            # Structured artifacts from the layered extractor — consumed by the
            # LangGraph summarizer (results tables) and downstream agents.
            'tables_md': getattr(extraction, 'tables_md', []) or [],
            # Structured tables (caption, page, markdown) for display — tables_md
            # above is the flattened form the summariser reads.
            'tables': [
                {
                    'markdown': t.markdown,
                    'caption': t.caption,
                    'label': t.label,
                    'page': t.page_number,
                    'n_rows': t.n_rows,
                    'n_cols': t.n_cols,
                }
                for t in (getattr(extraction, 'tables', []) or [])
            ],
            'equations': getattr(extraction, 'equations', []) or [],
            'metadata': {
                'section_count': len(sections),
                'total_words': total_words,
                'domain_match': domain_match,
                'expected_sections': expected_sections,
                'has_expected_structure': all(s in sections for s in expected_sections[:3]),
                'figures_pre_extracted': len(self._pre_extracted_figures),
                'extraction_backend': getattr(extraction, 'backend', 'unknown'),
                # table_count is the structured tables list the UI renders;
                # table_markdown_count is what the summariser reads. These used to
                # collide under one 'table_count' key computed from tables_md, so the
                # UI's own table count (len(extraction.tables)) was never the number
                # actually surfaced here. On a MinerU paper the two can genuinely
                # differ — tables_md may be MinerU's own extraction, not this one's.
                'table_count': len(getattr(extraction, 'tables', []) or []),
                'table_markdown_count': len(getattr(extraction, 'tables_md', []) or []),
                # Set only when table extraction itself raised, not merely when it
                # found none — lets the UI distinguish "no tables in this paper"
                # from "table extraction failed" instead of showing the same
                # empty state for both.
                'table_extraction_error': (extraction.metadata or {}).get('table_extraction_error'),
                # Recovered from page-1 layout by the extractor. Empty when it
                # couldn't be determined — callers fall back to the filename
                # rather than inventing a placeholder.
                'title': (extraction.metadata or {}).get('title', ''),
                'authors': (extraction.metadata or {}).get('authors', []) or [],
            }
        }
    
    def _extract_via_pymupdf4llm(self, pdf_path: str) -> Dict[str, str]:
        """Thin shim retained for backwards compatibility and tests.

        Delegates to the pdf_extractor pipeline (pymupdf4llm backend).
        """
        from core.pipeline.pdf_extractor import _extract_pymupdf4llm, ExtractionResult
        import tempfile, pathlib
        tmp = pathlib.Path(tempfile.mkdtemp())
        result = _extract_pymupdf4llm(pdf_path, tmp)
        return result.sections if result else {}

    async def _update_section_template(self, domain: str, section_sequence: List[str]):
        """Update learned section templates in experience DB."""
        # This would update section_templates table
        # For now, just track locally
        pass
    
    def _infer_domain(self, sections: Dict[str, str]) -> str:
        """Infer paper domain from content."""
        all_text = ' '.join(sections.values()).lower()
        
        # Simple keyword-based domain detection
        cv_keywords = ['image', 'vision', 'detection', 'segmentation', 'cnn', 'visual']
        nlp_keywords = ['language', 'text', 'nlp', 'translation', 'bert', 'transformer']
        ml_keywords = ['learning', 'training', 'model', 'neural', 'optimization']
        
        cv_score = sum(1 for kw in cv_keywords if kw in all_text)
        nlp_score = sum(1 for kw in nlp_keywords if kw in all_text)
        ml_score = sum(1 for kw in ml_keywords if kw in all_text)
        
        max_score = max(cv_score, nlp_score, ml_score)
        
        if cv_score == max_score and cv_score > 3:
            return 'cv'
        elif nlp_score == max_score and nlp_score > 3:
            return 'nlp'
        elif ml_score > 5:
            return 'ml'
        return 'general'
    
    async def handle_message(self, message):
        """Handle requests from other agents."""
        from core.agents.message_bus import MessageType
        
        if message.msg_type == MessageType.REQUEST:
            question = message.payload.get('question', '')
            
            # Handle "Where is X mentioned?" queries
            if 'where' in question.lower() and 'mentioned' in question.lower():
                entity = message.payload.get('context', {}).get('entity', '')
                sections_found = []
                
                for section_name, text in self.current_sections.items():
                    if entity.lower() in text.lower():
                        sections_found.append(section_name)
                
                response = {
                    'sections': sections_found,
                    'confidence': 0.9 if sections_found else 0.0,
                    'agent': self.name
                }
                
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response
                )
            
            # Handle "Get section content" queries
            elif 'get section' in question.lower():
                section_name = message.payload.get('context', {}).get('section', '')
                content = self.current_sections.get(section_name, '')
                
                response = {
                    'content': content,
                    'word_count': len(content.split()),
                    'confidence': 1.0 if content else 0.0,
                    'agent': self.name
                }
                
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response
                )
            else:
                # Default response
                await super().handle_message(message)
    
    def get_capabilities(self) -> List[str]:
        """Return agent capabilities."""
        return [
            'extract_sections',
            'query_section_location',
            'infer_domain',
            'learn_section_patterns',
            'learn_font_configurations',
            'multi_column_detection'
        ]
    
    async def _get_domain_font_config(self, domain: str) -> Optional[Dict[str, float]]:
        """Retrieve learned font configuration for a domain from experience DB.
        
        Uses weighted average of successful extractions in this domain.
        Falls back to default config if no domain data exists.
        """
        # Check cache first
        if domain in self.domain_font_cache:
            return self.domain_font_cache[domain]
        
        if not self.experience or not self.experience.enabled:
            return None
        
        try:
            # Query for font patterns in this domain
            # This would query a font_configurations table in Supabase
            # For now, return None to use default heuristics
            # TODO: Implement when experience DB schema is extended
            
            # Example of what the query would return:
            # results = await self.experience.query_font_config(domain)
            # if results and len(results) > 0:
            #     # Calculate weighted average based on success rate
            #     total_weight = sum(r['success_count'] for r in results)
            #     avg_percentile = sum(r['percentile'] * r['success_count'] 
            #                         for r in results) / total_weight
            #     avg_strong = sum(r['strong_percentile'] * r['success_count'] 
            #                     for r in results) / total_weight
            #     
            #     config = {
            #         'percentile': avg_percentile,
            #         'strong_percentile': avg_strong
            #     }
            #     self.domain_font_cache[domain] = config
            #     return config
            
            return None  # Fall back to default for now
            
        except Exception as e:
            logger.warning(f"Could not retrieve font config for domain '{domain}': {e}")
            return None
    
    async def _store_font_config(self, domain: str, min_header: float, strong_header: float):
        """Store successful font configuration for domain learning.
        
        Args:
            domain: Paper domain (cv, nlp, ml, general)
            min_header: The min_header_font_size that worked
            strong_header: The strong_header_font_size that worked
        """
        if not self.experience or not self.experience.enabled:
            return
        
        try:
            # Calculate percentiles from font sizes for storage
            # Since we used percentile-based approach, store the percentiles used
            percentile = self.font_config.get('percentile', 75)
            strong_percentile = self.font_config.get('strong_percentile', 90)
            
            # This would update font_configurations table in Supabase
            # TODO: Implement when experience DB schema is extended
            
            # Example of what would be stored:
            # await self.experience.store_font_config(
            #     domain=domain,
            #     percentile=percentile,
            #     strong_percentile=strong_percentile,
            #     min_header_size=min_header,
            #     strong_header_size=strong_header,
            #     success=True  # Assuming extraction was successful
            # )
            
            logger.info(f"Would store font config for domain '{domain}': "
                       f"p{percentile}={min_header:.1f}, p{strong_percentile}={strong_header:.1f}")
            
        except Exception as e:
            logger.warning(f"Could not store font config for domain '{domain}': {e}")
    
    def get_section(self, section_name: str) -> Optional[str]:
        """Get content of a specific section."""
        return self.current_sections.get(section_name)
    
    def has_section(self, section_name: str) -> bool:
        """Check if a section exists."""
        return section_name in self.current_sections
    
    def get_all_sections(self) -> Dict[str, str]:
        """Get all extracted sections."""
        return self.current_sections.copy()
