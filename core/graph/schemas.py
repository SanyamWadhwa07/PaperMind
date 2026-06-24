"""Domain-agnostic structured-output schemas for the summarization graph.

These Pydantic models are passed to ``llm.with_structured_output(...)`` so the
LLM returns typed JSON instead of free text. They deliberately avoid ML-specific
vocabulary (no "models"/"datasets"/"metrics") so the same extraction works for a
biomedical paper on pituitary tumours, an HCI study, or a transformers paper.

The four entity buckets map cleanly onto any empirical paper:
    method      — what was *done*: algorithm, model, technique, intervention, procedure
    material    — what it was done *on/with*: dataset, cohort, corpus, reagent, sample
    measurement — what was *measured*: metric, clinical outcome, score, endpoint
    tool        — what it was done *using*: framework, software, instrument, library

The field descriptions are part of the prompt — keep them concrete and specific,
they materially affect extraction quality.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

EntityKind = Literal["method", "material", "measurement", "tool"]


class Entity(BaseModel):
    """A salient named concept extracted from the paper."""

    name: str = Field(description="The exact name as written in the paper, e.g. 'BERT', 'ImageNet', 'transsphenoidal surgery', 'progression-free survival'.")
    kind: EntityKind = Field(description="method = algorithm/model/technique/intervention; material = dataset/cohort/corpus/sample; measurement = metric/clinical outcome/score; tool = framework/software/instrument.")
    description: str = Field(default="", description="One short clause on what it is or its role in THIS paper. Empty if not stated.")


class ResultRow(BaseModel):
    """One quantitative result, normalised for a comparison table."""

    measurement: str = Field(description="What was measured, e.g. 'accuracy', 'BLEU', '5-year survival rate', 'tumour volume reduction'.")
    value: str = Field(description="The reported value with units/percent as written, e.g. '92.3%', '0.41', '14.2 months'.")
    method: str = Field(default="", description="The method/model/intervention this value belongs to. Empty if unspecified.")
    subject: str = Field(default="", description="What it was measured on: dataset, cohort, patient group, or benchmark. Empty if unspecified.")
    is_best: bool = Field(default=False, description="True if the paper presents this as its best / headline / proposed-method result.")


class PaperEntities(BaseModel):
    """All salient entities extracted from a paper, bucketed by kind."""

    entities: List[Entity] = Field(default_factory=list, description="Up to ~25 of the most important named concepts across all four kinds. Prefer specific named things over generic words.")


class PaperResults(BaseModel):
    """Quantitative results extracted from results/experiments sections + tables."""

    results: List[ResultRow] = Field(default_factory=list, description="Every concrete quantitative result you can find. Pull numbers from tables and prose. Empty list if the paper reports none.")


class SectionDigest(BaseModel):
    """Compressed, faithful digest of a single paper section (map step)."""

    summary: str = Field(description="A faithful 2-4 sentence digest of this section. No fabrication; only what the text states.")
    facts: List[str] = Field(default_factory=list, description="Up to 5 atomic factual claims or numbers from this section, each a standalone sentence.")


class PaperSynthesis(BaseModel):
    """Final synthesis of the whole paper (reduce step)."""

    summary: str = Field(description="A 300-450 word flowing-prose analysis: the problem, the approach, the key results with concrete numbers, and why it matters. No bullet points, no markdown headers.")
    contributions: List[str] = Field(default_factory=list, description="2-4 primary contributions, each a concrete standalone sentence.")
    key_findings: List[str] = Field(default_factory=list, description="3-5 specific findings, each including a number or concrete detail from the paper.")
    limitations: List[str] = Field(default_factory=list, description="1-3 limitations actually stated or clearly implied by the paper. Empty list if none.")
    future_work: List[str] = Field(default_factory=list, description="1-3 future directions the paper suggests. Empty list if none.")


RelationType = Literal[
    "extends",            # B builds directly on A's method/idea
    "replicates",         # B reproduces/confirms A's results
    "contradicts",        # B's findings conflict with A's
    "applies_to_domain",  # B applies A's method to a new domain/dataset
    "shares_method",      # independent works using the same core method
    "shares_dataset",     # evaluated on the same dataset/cohort/benchmark
    "compares_against",   # one uses the other as a baseline
    "unrelated",          # no meaningful relationship
]


class PaperRelation(BaseModel):
    """A typed, explained relationship between two papers (RelationAgent output)."""

    relationship: RelationType = Field(description="The single most salient relationship between paper A and paper B.")
    direction: Literal["a_to_b", "b_to_a", "bidirectional", "none"] = Field(
        description="a_to_b = A precedes/B builds on A; b_to_a = reverse; bidirectional = mutual/peer; none = unrelated."
    )
    confidence: float = Field(description="Confidence in this relationship, 0.0 to 1.0.")
    explanation: str = Field(description="One or two sentences justifying the relationship, citing the concrete shared method/dataset/finding.")
    shared_entities: List[str] = Field(default_factory=list, description="Specific methods/datasets/measurements both papers share. Empty if none.")


class SummaryGrade(BaseModel):
    """LLM-as-judge grade of a synthesis, used to decide whether to retry (grade step)."""

    faithful: bool = Field(description="True if every claim in the summary is supported by the source digests (no hallucinated methods/numbers).")
    specific: bool = Field(description="True if the summary names concrete methods/materials and includes real numbers, rather than vague generalities.")
    score: float = Field(description="Overall quality from 0.0 to 1.0.")
    issues: List[str] = Field(default_factory=list, description="Concrete problems to fix on a retry. Empty if none.")
