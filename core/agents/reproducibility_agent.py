"""ReproducibilityAgent — scores how reproducible a paper is (0-10 rubric)."""

import sys
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Regex patterns per rubric criterion
CRITERIA: List[Dict] = [
    {
        "name": "code_available",
        "points": 2,
        "patterns": [
            r"github\.com/[\w\-]+/[\w\-]+",
            r"code (?:is )?(?:available|released|open.sourced)",
            r"implementation (?:is )?(?:available|public)",
            r"we release",
            r"open.source",
        ],
    },
    {
        "name": "datasets_named",
        "points": 2,
        "patterns": [
            r"\b(?:ImageNet|COCO|SQuAD|GLUE|SuperGLUE|WikiText|Penn Treebank|"
            r"CIFAR|MNIST|MS\s*COCO|VQA|CelebA|LAION|C4|The Pile|OpenWebText|"
            r"SNLI|MultiNLI|CoQA|TriviaQA|HotpotQA)\b",
        ],
        "description": "dataset names mentioned",
    },
    {
        "name": "hyperparameters_reported",
        "points": 2,
        "patterns": [
            r"learning rate[:\s]+[\d.e-]+",
            r"batch size[:\s]+\d+",
            r"(?:dropout|weight decay|momentum)[:\s]+[\d.]+",
            r"(?:epochs?|iterations?)[:\s]+\d+",
            r"optimizer[:\s]+\w+",
        ],
    },
    {
        "name": "random_seeds",
        "points": 1,
        "patterns": [
            r"\b(?:random )?seed[s]?[:\s]+\d+",
            r"fixed seed",
            r"reproducib(?:le|ility)",
        ],
    },
    {
        "name": "compute_stated",
        "points": 1,
        "patterns": [
            r"\b(?:GPU|TPU|A100|V100|RTX|H100)\b",
            r"\d+\s*(?:GPU|TPU)s?",
            r"trained (?:on|using) [\d]+",
            r"compute budget",
        ],
    },
    {
        "name": "statistical_significance",
        "points": 1,
        "patterns": [
            r"statistical(?:ly)? significant",
            r"p[- ]?value[s]?[:\s]+[\d.]+",
            r"confidence interval",
            r"standard deviation",
            r"variance across",
            r"error bars",
        ],
    },
    {
        "name": "pseudocode_present",
        "points": 1,
        "patterns": [
            r"(?:algorithm|pseudo.?code|pseudocode)\s+\d",
            r"\\begin\{algorithm\}",
            r"Algorithm\s+\d+[:\.]",
        ],
    },
]

GITHUB_RE = re.compile(r"https?://github\.com/([\w\-]+)/([\w\-]+)", re.IGNORECASE)


class ReproducibilityAgent(BaseAgent):
    """Scores paper reproducibility on a 0-10 rubric using regex criterion checks."""

    def __init__(self, patterns: Optional[Dict] = None, llm_config: Optional[Dict] = None):
        super().__init__(name="ReproducibilityAgent", patterns=patterns)

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        sections: Dict[str, str] = input_data.get("sections", {})
        full_text = " ".join(sections.values())

        score = 0
        evidence: Dict[str, Any] = {}
        github_links: List[str] = GITHUB_RE.findall(full_text)
        github_urls = [f"https://github.com/{o}/{r}" for o, r in github_links]

        for criterion in CRITERIA:
            matched = any(
                re.search(p, full_text, re.IGNORECASE)
                for p in criterion["patterns"]
            )
            if matched:
                score += criterion["points"]
            evidence[criterion["name"]] = matched

        # Code availability gets confirmed by GitHub link presence too
        if github_urls and not evidence.get("code_available"):
            score += 1  # partial credit
            evidence["code_available"] = True
            evidence["code_available_partial"] = True

        score = min(score, 10)

        repro_data = {
            "score": score,
            "max_score": 10,
            "evidence": evidence,
            "github_links": list(set(github_urls))[:10],
        }

        return {
            "extractions": list(evidence.keys()),
            "confidence_scores": {"reproducibility": 0.9},
            "reproducibility": repro_data,
            "metadata": {
                "score": score,
                "github_link_count": len(github_urls),
            },
        }

    def get_capabilities(self) -> List[str]:
        return ["score_reproducibility", "extract_github_links", "check_hyperparameters"]
