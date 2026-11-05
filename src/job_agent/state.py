"""Graph state and the structured outputs the LLM produces.

LangGraph passes one shared state object between nodes. Each node returns a
*partial* update (a dict with only the keys it changed) and LangGraph merges it
into the state. Everything in here is saved by the checkpointer after every
step, which is what makes pause/resume and crash recovery possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

# --- Structured LLM outputs -------------------------------------------------


class JobAnalysis(BaseModel):
    title: str
    company: str = Field(description="Company name, or 'Unknown' if not stated")
    seniority: str = Field(description="e.g. junior, mid, senior, staff, lead")
    summary: str = Field(description="Two sentences on what this role actually does")
    must_have: list[str] = Field(description="Hard requirements explicitly stated")
    nice_to_have: list[str] = Field(description="Preferred / bonus qualifications")
    keywords: list[str] = Field(
        description="Tools, technologies and domain terms an ATS would scan for"
    )


class Evidence(BaseModel):
    requirement: str
    evidence: str = Field(description="Where in the resume this is demonstrated")


class FitReport(BaseModel):
    score: int = Field(ge=0, le=100, description="Honest overall fit, 0-100")
    verdict: str = Field(description="One-sentence honest assessment")
    strengths: list[Evidence]
    gaps: list[str] = Field(description="Requirements the resume does not show")
    positioning: str = Field(
        description="How the candidate should frame their experience for this role"
    )


class FactCheck(BaseModel):
    passed: bool = Field(
        description="True only if every claim in both drafts is supported by the original resume"
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Each unsupported or exaggerated claim, quoted, with what the resume actually says",
    )


class RevisedDocuments(BaseModel):
    resume: str = Field(description="The full revised resume in Markdown")
    cover_letter: str = Field(description="The full revised cover letter")


# --- Human review protocol --------------------------------------------------


class ReviewDecision(TypedDict, total=False):
    """What a client sends back to resume the graph after `human_review`."""

    action: Literal["approve", "revise"]
    feedback: str


# --- Graph state ------------------------------------------------------------


class AgentState(TypedDict, total=False):
    # Inputs
    job_url: str
    job_text: str
    resume_text: str

    # Analysis (stored as plain dicts so checkpoints are plain JSON)
    job: dict  # JobAnalysis
    fit: dict  # FitReport

    # Drafts (written in parallel, then revised in loops)
    resume_draft: str
    cover_letter_draft: str

    # Quality loop
    fact_check: dict  # FactCheck
    auto_revisions: int
    human_feedback: str
    human_revisions: int

    approved: bool


# --- Run-scoped context (not saved in checkpoints) --------------------------


@dataclass
class AgentContext:
    """Per-run settings. Passed with `graph.invoke(..., context=AgentContext(...))`.

    Kept out of the state so secrets like the API key are never written to the
    checkpoint database.
    """

    anthropic_api_key: str | None = None
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_auto_revisions: int = 2
