"""ReasoningAgent - Extracts causal chains and validates claims.

New algorithmic agent (no direct main.py wrapper):
- Build claim-evidence graphs
- Extract causal relationships
- Validate logical consistency
- Cross-check with other agents
"""

import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
import re

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState


class ReasoningAgent(BaseAgent):
    """
    Agent responsible for reasoning analysis and validation.
    
    Capabilities:
    - Extract claims and evidence
    - Build causal chains
    - Validate logical consistency
    - Detect unsupported claims
    - Cross-validate with results
    """
    
    def __init__(self, patterns: Optional[Dict] = None):
        super().__init__(name="ReasoningAgent", patterns=patterns)
        self.claims: List[Dict] = []
        self.causal_chains: List[Dict] = []
        self.unsupported_claims: List[str] = []
    
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze reasoning structure.
        
        Args:
            input_data: {
                'sections': Dict[str, str] - Section content
                'results': List[Dict] - Results from ResultsAgent
                'entities': Dict - Entities from EntityAgent
            }
        
        Returns:
            {
                'extractions': List of claims/chains,
                'confidence_scores': Dict mapping claim_id -> confidence,
                'reasoning': {
                    'claims': List[Dict],
                    'causal_chains': List[Dict],
                    'unsupported_claims': List[str]
                },
                'metadata': {
                    'total_claims': int,
                    'validated_claims': int,
                    'causal_chain_count': int
                }
            }
        """
        sections = input_data.get('sections', {})
        results = input_data.get('results', [])
        entities = input_data.get('entities', {})
        
        if not sections:
            raise ValueError("sections required")
        
        # Focus on key reasoning sections
        abstract = sections.get('abstract', '')
        introduction = sections.get('introduction', '')
        methodology = sections.get('methodology', '')
        conclusion = sections.get('conclusion', '')
        
        combined_text = abstract + ' ' + introduction + ' ' + methodology + ' ' + conclusion
        
        # Extract claims
        claims = self._extract_claims(combined_text)
        self.claims = claims
        
        # Build causal chains
        causal_chains = self._extract_causal_chains(combined_text)
        self.causal_chains = causal_chains
        
        # Validate claims against results
        validated_claims, unsupported = await self._validate_claims(claims, results)
        self.unsupported_claims = unsupported
        
        # Calculate confidence scores
        confidence_scores = {}
        
        for i, claim in enumerate(claims):
            claim_id = f"claim_{i}"
            
            # Base confidence
            confidence = 0.5
            
            # Boost if claim has evidence
            if claim.get('evidence'):
                confidence += 0.2
            
            # Boost if claim references results
            if claim.get('result_reference'):
                confidence += 0.2
            
            # Reduce if claim is unsupported
            if claim.get('text', '') in unsupported:
                confidence = 0.3
            
            confidence_scores[claim_id] = min(confidence, 1.0)
        
        all_extractions = claims + causal_chains
        
        return {
            'extractions': all_extractions,
            'confidence_scores': confidence_scores,
            'reasoning': {
                'claims': claims,
                'causal_chains': causal_chains,
                'unsupported_claims': unsupported
            },
            'metadata': {
                'total_claims': len(claims),
                'validated_claims': len(validated_claims),
                'causal_chain_count': len(causal_chains),
                'unsupported_count': len(unsupported)
            }
        }
    
    def _extract_claims(self, text: str) -> List[Dict]:
        """
        Extract claims from text.
        
        Patterns:
        - "We show that..."
        - "Our method achieves..."
        - "X leads to Y"
        - "X outperforms Y"
        """
        claims = []
        
        claim_patterns = [
            r'(?:we|our method|our approach) (?:show|demonstrate|prove|find|achieve)s? that ([^.]+)',
            r'(?:this|our) (?:results?|findings?|work) (?:shows?|demonstrates?|indicates?) that ([^.]+)',
            r'([^.]+?) (?:outperforms?|exceeds?|surpasses?) ([^.]+)',
            r'([^.]+?) (?:leads? to|results? in|causes?) ([^.]+)',
            r'we (?:propose|introduce|present) ([^.]+)',
        ]
        
        for pattern in claim_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                claim_text = match.group(0)
                claims.append({
                    'text': claim_text,
                    'type': 'performance' if 'outperform' in claim_text.lower() else 'finding',
                    'evidence': None,
                    'result_reference': False
                })
        
        return claims[:20]  # Limit to top 20 claims
    
    def _extract_causal_chains(self, text: str) -> List[Dict]:
        """
        Extract causal relationships.
        
        Patterns:
        - "X leads to Y"
        - "Because of X, Y"
        - "X enables Y"
        - "By doing X, we achieve Y"
        """
        chains = []
        
        causal_patterns = [
            (r'([^.]+?) (?:leads? to|results? in) ([^.]+)', 'leads_to'),
            (r'because (?:of )?([^,]+), ([^.]+)', 'because'),
            (r'([^.]+?) (?:enables?|allows?) ([^.]+)', 'enables'),
            (r'by (?:using |doing )?([^,]+), (?:we )?(?:achieve|obtain) ([^.]+)', 'by_doing'),
        ]
        
        for pattern, chain_type in causal_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 2:
                    cause = match.group(1).strip()
                    effect = match.group(2).strip()
                    
                    chains.append({
                        'cause': cause,
                        'effect': effect,
                        'type': chain_type,
                        'text': match.group(0)
                    })
        
        return chains[:15]  # Limit to top 15 chains
    
    async def _validate_claims(
        self, 
        claims: List[Dict], 
        results: List[Dict]
    ) -> Tuple[List[Dict], List[str]]:
        """
        Validate claims against experimental results.
        
        Returns:
            (validated_claims, unsupported_claims)
        """
        validated = []
        unsupported = []
        
        # Create result lookup
        result_texts = [str(r.get('value', '')) + ' ' + r.get('metric', '') for r in results]
        
        for claim in claims:
            claim_text = claim.get('text', '').lower()
            
            # Check if claim references any result
            has_evidence = False
            
            for result in results:
                metric = result.get('metric', '').lower()
                value = str(result.get('value', ''))
                dataset = result.get('dataset', '').lower()
                
                # Simple check: does claim mention metric/dataset/value?
                if (metric in claim_text or 
                    dataset in claim_text or 
                    value in claim_text):
                    has_evidence = True
                    claim['evidence'] = result
                    claim['result_reference'] = True
                    break
            
            if has_evidence:
                validated.append(claim)
            else:
                # Performance claims without evidence are problematic
                if claim.get('type') == 'performance':
                    unsupported.append(claim.get('text', ''))
        
        return validated, unsupported
    
    async def handle_message(self, message):
        """Handle requests from other agents."""
        from core.agents.message_bus import MessageType
        
        if message.msg_type == MessageType.REQUEST:
            question = message.payload.get('question', '')
            
            # Handle "Are there unsupported claims?" queries
            if 'unsupported' in question.lower():
                response = {
                    'has_unsupported': len(self.unsupported_claims) > 0,
                    'unsupported_claims': self.unsupported_claims,
                    'count': len(self.unsupported_claims),
                    'confidence': 0.9,
                    'agent': self.name
                }
                
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response
                )
            
            # Handle "Get causal chains" queries
            elif 'causal' in question.lower():
                response = {
                    'causal_chains': self.causal_chains,
                    'count': len(self.causal_chains),
                    'confidence': 0.8,
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
            'extract_claims',
            'extract_causal_chains',
            'validate_claims',
            'detect_unsupported_claims',
            'analyze_logical_consistency'
        ]
    
    def get_all_claims(self) -> List[Dict]:
        """Get all extracted claims."""
        return self.claims.copy()
    
    def get_causal_chains(self) -> List[Dict]:
        """Get all causal chains."""
        return self.causal_chains.copy()
    
    def get_unsupported_claims(self) -> List[str]:
        """Get claims without evidence."""
        return self.unsupported_claims.copy()
