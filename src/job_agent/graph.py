"""The graph wiring. Read this file first to understand the agent's flow.

    START
      │
    ingest ─────────────── fetch the job URL (retried on network errors)
      │
    analyze_job ────────── structured JobAnalysis
      │
    assess_fit ─────────── structured FitReport (score, evidence, gaps)
      │
      ├──────────────┐     fan-out: both run in parallel
    tailor_resume  write_cover_letter
      ├──────────────┘     fan-in: fact_check waits for both
      │
    fact_check ◄──────┐    guardrail against fabricated claims
      │               │
      ├─ issues? ─► revise ◄─┐
      │                       │
    human_review ── feedback ─┘   ⏸ interrupt(): waits for a person
      │
     END (approved)
"""

from __future__ import annotations

import httpx
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.types import RetryPolicy

from job_agent import nodes
from job_agent.state import AgentContext, AgentState


def _retry_network(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(AgentState, context_schema=AgentContext)

    builder.add_node(
        "ingest",
        nodes.ingest,
        retry_policy=RetryPolicy(max_attempts=3, retry_on=_retry_network),
    )
    builder.add_node("analyze_job", nodes.analyze_job)
    builder.add_node("assess_fit", nodes.assess_fit)
    builder.add_node("tailor_resume", nodes.tailor_resume)
    builder.add_node("write_cover_letter", nodes.write_cover_letter)
    builder.add_node("fact_check", nodes.fact_check)
    builder.add_node("revise", nodes.revise)
    builder.add_node("human_review", nodes.human_review)

    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "analyze_job")
    builder.add_edge("analyze_job", "assess_fit")

    # Fan-out: two edges from one node run both targets in the same step.
    builder.add_edge("assess_fit", "tailor_resume")
    builder.add_edge("assess_fit", "write_cover_letter")
    # Fan-in: a list of sources means "wait until all of them have finished".
    builder.add_edge(["tailor_resume", "write_cover_letter"], "fact_check")

    builder.add_conditional_edges("fact_check", nodes.route_after_fact_check)
    builder.add_edge("revise", "fact_check")
    # human_review routes itself with Command(goto=...) to "revise" or END.

    return builder.compile(checkpointer=checkpointer)


# Entry point for `langgraph dev` / LangGraph Platform, which supply their own
# checkpointer. Local clients call build_graph(checkpointer=...) instead.
graph = build_graph()
