"""Model construction. Nodes call `get_model` so tests can swap in a fake."""

from __future__ import annotations

import os

from langchain_anthropic import ChatAnthropic

from job_agent.state import AgentContext


def get_model(ctx: AgentContext | None) -> ChatAnthropic:
    ctx = ctx or AgentContext()
    return ChatAnthropic(
        model=os.getenv("JOB_AGENT_MODEL", ctx.model),
        api_key=ctx.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"),
        effort=os.getenv("JOB_AGENT_EFFORT", ctx.effort),
        max_tokens=16000,
        max_retries=3,
    )


def structured(ctx: AgentContext | None, schema: type):
    # json_schema uses Claude's native structured outputs. The default
    # (forced tool calling) isn't supported on current Claude models.
    return get_model(ctx).with_structured_output(schema, method="json_schema")
