"""Graph nodes. Each is a plain function: (state, runtime) -> partial state update."""

from __future__ import annotations

import json
from typing import Literal

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from job_agent import llm, prompts
from job_agent.state import (
    AgentContext,
    AgentState,
    FactCheck,
    FitReport,
    JobAnalysis,
    ReviewDecision,
    RevisedDocuments,
)
from job_agent.tools import fetch_job_posting

Ctx = Runtime[AgentContext]


def _msgs(prompt: str) -> list[tuple[str, str]]:
    return [("system", prompts.SYSTEM), ("user", prompt)]


def _dump(d: dict) -> str:
    return json.dumps(d, indent=2)


# --- Ingest & analysis ------------------------------------------------------


def ingest(state: AgentState) -> dict:
    """Get the job text, fetching the URL if the user didn't paste it."""
    if not state.get("resume_text", "").strip():
        raise ValueError("resume_text is required")
    if state.get("job_text", "").strip():
        return {}
    if not state.get("job_url"):
        raise ValueError("Provide either job_text or job_url")
    return {"job_text": fetch_job_posting(state["job_url"])}


def analyze_job(state: AgentState, runtime: Ctx) -> dict:
    job: JobAnalysis = llm.structured(runtime.context, JobAnalysis).invoke(
        _msgs(prompts.ANALYZE_JOB.format(job_text=state["job_text"]))
    )
    return {"job": job.model_dump()}


def assess_fit(state: AgentState, runtime: Ctx) -> dict:
    fit: FitReport = llm.structured(runtime.context, FitReport).invoke(
        _msgs(prompts.ASSESS_FIT.format(job=_dump(state["job"]), resume=state["resume_text"]))
    )
    return {"fit": fit.model_dump()}


# --- Drafting (these two run in parallel) -----------------------------------


def tailor_resume(state: AgentState, runtime: Ctx) -> dict:
    msg = llm.get_model(runtime.context).invoke(
        _msgs(
            prompts.TAILOR_RESUME.format(
                job=_dump(state["job"]), fit=_dump(state["fit"]), resume=state["resume_text"]
            )
        )
    )
    return {"resume_draft": msg.text.strip()}


def write_cover_letter(state: AgentState, runtime: Ctx) -> dict:
    msg = llm.get_model(runtime.context).invoke(
        _msgs(
            prompts.COVER_LETTER.format(
                job=_dump(state["job"]), fit=_dump(state["fit"]), resume=state["resume_text"]
            )
        )
    )
    return {"cover_letter_draft": msg.text.strip()}


# --- Quality loop -----------------------------------------------------------


def fact_check(state: AgentState, runtime: Ctx) -> dict:
    """Guardrail: a second LLM pass that hunts for fabricated claims."""
    result: FactCheck = llm.structured(runtime.context, FactCheck).invoke(
        _msgs(
            prompts.FACT_CHECK.format(
                resume=state["resume_text"],
                resume_draft=state["resume_draft"],
                cover_letter_draft=state["cover_letter_draft"],
            )
        )
    )
    # A "pass" with listed issues is contradictory; trust the issues.
    passed = result.passed and not result.issues
    return {"fact_check": {"passed": passed, "issues": result.issues}}


def route_after_fact_check(
    state: AgentState, runtime: Ctx
) -> Literal["revise", "human_review"]:
    """Conditional edge: auto-fix fabrications, but cap the loop."""
    if state["fact_check"]["passed"]:
        return "human_review"
    if state.get("auto_revisions", 0) >= runtime.context.max_auto_revisions:
        # Out of budget: let the human see the remaining issues and decide.
        return "human_review"
    return "revise"


def revise(state: AgentState, runtime: Ctx) -> dict:
    """Revise from human feedback if there is any, otherwise from fact-check issues."""
    human = state.get("human_feedback", "").strip()
    if human:
        feedback = human
    else:
        feedback = "Fix these unsupported claims:\n" + "\n".join(
            f"- {issue}" for issue in state["fact_check"]["issues"]
        )

    docs: RevisedDocuments = llm.structured(runtime.context, RevisedDocuments).invoke(
        _msgs(
            prompts.REVISE.format(
                feedback=feedback,
                job=_dump(state["job"]),
                resume=state["resume_text"],
                resume_draft=state["resume_draft"],
                cover_letter_draft=state["cover_letter_draft"],
            )
        )
    )
    update: dict = {
        "resume_draft": docs.resume.strip(),
        "cover_letter_draft": docs.cover_letter.strip(),
        "human_feedback": "",
    }
    if not human:
        update["auto_revisions"] = state.get("auto_revisions", 0) + 1
    return update


# --- Human in the loop ------------------------------------------------------


def human_review(state: AgentState) -> Command[Literal["revise", "__end__"]]:
    """Pause the graph until a person approves or asks for changes.

    `interrupt()` saves the state and stops. The client shows the payload to the
    user, then resumes with `Command(resume={"action": ..., "feedback": ...})`.
    When resumed, this node re-runs from the top and `interrupt()` returns that
    value instead of pausing.
    """
    decision: ReviewDecision = interrupt(
        {
            "fit": state["fit"],
            "resume_draft": state["resume_draft"],
            "cover_letter_draft": state["cover_letter_draft"],
            "fact_check": state["fact_check"],
        }
    )

    feedback = (decision.get("feedback") or "").strip()
    if decision.get("action") == "revise" and feedback:
        return Command(
            goto="revise",
            update={
                "human_feedback": feedback,
                "human_revisions": state.get("human_revisions", 0) + 1,
                # Fresh fact-check budget for each round of human feedback.
                "auto_revisions": 0,
            },
        )
    return Command(goto=END, update={"approved": True})
