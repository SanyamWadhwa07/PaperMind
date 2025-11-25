"""FigureAgent - Extracts and ranks figures/tables.

Wraps existing FigureExtractor with agent capabilities:
- Extract figures and captions
- Rank by relevance
- Cross-reference with text mentions
"""

import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState
from backend.main import FigureExtractor


class FigureAgent(BaseAgent):
    """
    Agent responsible for figure and table extraction.
    
    Capabilities:
    - Extract figures with captions
    - Rank figures by relevance
    - Cross-reference figures with text
    - Extract table data
    """
    
    def __init__(self, patterns: Optional[Dict] = None):
        super().__init__(name="FigureAgent", patterns=patterns)
        self.figure_extractor = FigureExtractor()
        self.extracted_figures: List[Dict] = []
    
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract figures and tables from PDF.
        
        Args:
            input_data: {
                'pdf_path': str - Path to PDF file
                'sections': Dict[str, str] - Section content for context
            }
        
        Returns:
            {
                'extractions': List of figure dictionaries,
                'confidence_scores': Dict mapping figure_id -> confidence,
                'figures': List of figure data with rankings,
                'metadata': {
                    'total_figures': int,
                    'ranked_figures': List[str] - Top figures by relevance
                }
            }
        """
        pdf_path = input_data.get('pdf_path')
        sections = input_data.get('sections', {})
        
        if not pdf_path:
            raise ValueError("pdf_path required")
        
        # Extract figures using existing extractor
        figures = self.figure_extractor.extract_figures(pdf_path)
        self.extracted_figures = figures
        
        # Rank figures by relevance
        ranked_figures = self._rank_figures(figures, sections)
        
        # Assign confidence scores based on:
        # 1. Has caption (higher confidence)
        # 2. Referenced in text (higher confidence)
        # 3. Ranking position (higher = better)
        confidence_scores = {}
        
        for i, fig in enumerate(ranked_figures):
            fig_id = fig.get('id', f"fig_{i}")
            
            confidence = 0.5  # Base confidence
            
            # Boost for caption
            if fig.get('caption'):
                confidence += 0.2
            
            # Boost for text references
            if fig.get('references', 0) > 0:
                confidence += 0.2
            
            # Boost for high ranking
            if i < 3:
                confidence += 0.1
            
            confidence_scores[fig_id] = min(confidence, 1.0)
        
        return {
            'extractions': ranked_figures,
            'confidence_scores': confidence_scores,
            'figures': ranked_figures,
            'metadata': {
                'total_figures': len(figures),
                'ranked_figures': [f.get('id', f'fig_{i}') for i, f in enumerate(ranked_figures[:5])]
            }
        }
    
    def _rank_figures(self, figures: List[Dict], sections: Dict[str, str]) -> List[Dict]:
        """
        Rank figures by relevance.
        
        Scoring factors:
        - Mentioned in abstract/introduction (high priority)
        - Mentioned in results (medium priority)
        - Has detailed caption (bonus)
        - Position in paper (earlier = higher)
        """
        all_text = ' '.join(sections.values()).lower()
        abstract = sections.get('abstract', '').lower()
        introduction = sections.get('introduction', '').lower()
        results = sections.get('results', '').lower()
        
        scored_figures = []
        
        for i, fig in enumerate(figures):
            score = 0
            fig_id = fig.get('id', f'figure {i+1}').lower()
            caption = fig.get('caption', '').lower()
            
            # Count references in text
            references = all_text.count(fig_id)
            fig['references'] = references
            
            # Abstract/Introduction mentions (high value)
            if fig_id in abstract or fig_id in introduction:
                score += 10
            
            # Results section mentions (medium value)
            if fig_id in results:
                score += 5
            
            # Total references
            score += references * 2
            
            # Caption quality (longer = more informative)
            if caption:
                score += min(len(caption.split()) / 10, 5)
            
            # Position bonus (earlier figures often more important)
            score += (len(figures) - i) * 0.5
            
            fig['relevance_score'] = score
            scored_figures.append(fig)
        
        # Sort by score (descending)
        ranked = sorted(scored_figures, key=lambda x: x['relevance_score'], reverse=True)
        return ranked
    
    async def handle_message(self, message):
        """Handle requests from other agents."""
        from core.agents.message_bus import MessageType
        
        if message.msg_type == MessageType.REQUEST:
            question = message.payload.get('question', '')
            
            # Handle "Get top figures" queries
            if 'top' in question.lower() and 'figure' in question.lower():
                count = message.payload.get('context', {}).get('count', 3)
                top_figures = self.extracted_figures[:count]
                
                response = {
                    'figures': top_figures,
                    'count': len(top_figures),
                    'confidence': 0.9,
                    'agent': self.name
                }
                
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response
                )
            
            # Handle "Get figure X" queries
            elif 'get figure' in question.lower():
                fig_id = message.payload.get('context', {}).get('figure_id', '')
                figure = next((f for f in self.extracted_figures if f.get('id', '') == fig_id), None)
                
                response = {
                    'figure': figure,
                    'found': figure is not None,
                    'confidence': 1.0 if figure else 0.0,
                    'agent': self.name
                }
                
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response
                )
            else:
                await super().handle_message(message)
    
    def get_capabilities(self) -> List[str]:
        """Return agent capabilities."""
        return [
            'extract_figures',
            'extract_tables',
            'rank_by_relevance',
            'cross_reference_text',
            'analyze_captions'
        ]
    
    def get_top_figures(self, count: int = 3) -> List[Dict]:
        """Get top N figures by relevance."""
        return self.extracted_figures[:count]
    
    def get_all_figures(self) -> List[Dict]:
        """Get all extracted figures."""
        return self.extracted_figures.copy()
    
    def get_figure_by_id(self, fig_id: str) -> Optional[Dict]:
        """Get specific figure by ID."""
        return next((f for f in self.extracted_figures if f.get('id', '') == fig_id), None)
