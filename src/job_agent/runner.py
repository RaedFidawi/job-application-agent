"""Client-side helpers shared by the CLI and the web app.

The pattern for any human-in-the-loop LangGraph app:
  1. stream(inputs)            -> runs until the graph finishes or interrupts
  2. get_state(config)         -> check snapshot.interrupts for a pending pause
  3. stream(Command(resume=x)) -> continue from exactly where it paused
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.types import Command

from job_agent.state import AgentContext, ReviewDecision

STEP_LABELS = {
    "ingest": "Reading the job posting",
    "analyze_job": "Analysing the role",
    "assess_fit": "Assessing your fit",
    "tailor_resume": "Tailoring your resume",
    "write_cover_letter": "Writing your cover letter",
    "fact_check": "Fact-checking drafts against your resume",
    "revise": "Revising drafts",
    "human_review": "Recording your review",
}


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _run(graph, payload: Any, thread_id: str, ctx: AgentContext, on_step: Callable[[str], None] | None):
    for chunk in graph.stream(payload, _config(thread_id), context=ctx, stream_mode="updates"):
        for node in chunk:
            if on_step and node in STEP_LABELS:
                on_step(node)
    return graph.get_state(_config(thread_id))


def start(graph, inputs: dict, thread_id: str, ctx: AgentContext, on_step=None):
    return _run(graph, inputs, thread_id, ctx, on_step)


def resume(graph, decision: ReviewDecision, thread_id: str, ctx: AgentContext, on_step=None):
    return _run(graph, Command(resume=decision), thread_id, ctx, on_step)


def continue_after_crash(graph, thread_id: str, ctx: AgentContext, on_step=None):
    """Passing None as input re-runs from the last saved checkpoint."""
    return _run(graph, None, thread_id, ctx, on_step)


def pending_review(snapshot) -> dict | None:
    """The payload human_review is waiting on, or None if not paused there."""
    return snapshot.interrupts[0].value if snapshot.interrupts else None
