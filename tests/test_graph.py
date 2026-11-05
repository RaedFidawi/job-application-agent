"""Graph tests with a fake LLM: they check the control flow (parallel drafting,
the fact-check loop and its cap, interrupt/resume, human revisions) without
calling the API."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from job_agent import llm, runner
from job_agent.graph import build_graph
from job_agent.state import (
    AgentContext,
    Evidence,
    FactCheck,
    FitReport,
    JobAnalysis,
    RevisedDocuments,
)

JOB = JobAnalysis(
    title="Backend Engineer", company="Acme", seniority="mid", summary="Builds APIs.",
    must_have=["Python"], nice_to_have=["Kubernetes"], keywords=["Python", "FastAPI"],
)
FIT = FitReport(
    score=80, verdict="Strong fit.",
    strengths=[Evidence(requirement="Python", evidence="5 years at Foo")],
    gaps=["Kubernetes"], positioning="Lead with API work.",
)


class FakeLLM:
    def __init__(self, fact_checks: list[FactCheck]):
        self.fact_checks = list(fact_checks)
        self.calls: list[str] = []
        self.revision_feedback: list[str] = []
        self.revisions = 0

    # Plain text calls: tailor_resume and write_cover_letter
    def invoke(self, messages):
        prompt = messages[-1][1]
        kind = "resume" if "Rewrite the candidate's resume" in prompt else "cover_letter"
        self.calls.append(kind)
        return AIMessage(content=f"{kind} v0")

    def with_structured_output(self, schema, method=None):
        fake = self

        class Runnable:
            def invoke(self, messages):
                fake.calls.append(schema.__name__)
                if schema is JobAnalysis:
                    return JOB
                if schema is FitReport:
                    return FIT
                if schema is FactCheck:
                    return fake.fact_checks.pop(0) if fake.fact_checks else FactCheck(passed=True)
                if schema is RevisedDocuments:
                    fake.revisions += 1
                    fake.revision_feedback.append(messages[-1][1])
                    n = fake.revisions
                    return RevisedDocuments(resume=f"resume v{n}", cover_letter=f"cover_letter v{n}")
                raise AssertionError(schema)

        return Runnable()


@pytest.fixture
def fake(monkeypatch):
    def install(fact_checks=()):
        f = FakeLLM(list(fact_checks))
        monkeypatch.setattr(llm, "get_model", lambda ctx: f)
        return f

    return install


INPUTS = {"job_text": "We need a Python backend engineer.", "resume_text": "Python dev, 5 years at Foo."}
CTX = AgentContext(max_auto_revisions=2)


def new_graph():
    return build_graph(checkpointer=InMemorySaver())


def test_happy_path_pauses_for_review_then_approves(fake):
    f = fake([FactCheck(passed=True)])
    graph = new_graph()

    snap = runner.start(graph, INPUTS, "t1", CTX)
    review = runner.pending_review(snap)
    assert review is not None
    assert review["resume_draft"] == "resume v0"
    assert review["cover_letter_draft"] == "cover_letter v0"
    assert review["fit"]["score"] == 80
    # Both drafts were written before the single fact-check (fan-in).
    assert f.calls.index("FactCheck") > max(f.calls.index("resume"), f.calls.index("cover_letter"))

    snap = runner.resume(graph, {"action": "approve"}, "t1", CTX)
    assert runner.pending_review(snap) is None
    assert snap.values["approved"] is True
    assert snap.next == ()


def test_fact_check_failure_triggers_auto_revision(fake):
    f = fake([FactCheck(passed=False, issues=["Claims Kubernetes"]), FactCheck(passed=True)])
    snap = runner.start(new_graph(), INPUTS, "t2", CTX)

    review = runner.pending_review(snap)
    assert f.revisions == 1
    assert "Claims Kubernetes" in f.revision_feedback[0]
    assert review["resume_draft"] == "resume v1"
    assert review["fact_check"]["passed"] is True
    assert snap.values["auto_revisions"] == 1


def test_fact_check_loop_is_capped(fake):
    bad = FactCheck(passed=False, issues=["Still invented"])
    f = fake([bad, bad, bad, bad])
    snap = runner.start(new_graph(), INPUTS, "t3", CTX)

    review = runner.pending_review(snap)
    assert f.revisions == 2  # max_auto_revisions
    assert review["fact_check"]["passed"] is False  # human sees the remaining issues


def test_pass_with_issues_is_treated_as_fail(fake):
    f = fake([FactCheck(passed=True, issues=["Inflated title"]), FactCheck(passed=True)])
    runner.start(new_graph(), INPUTS, "t4", CTX)
    assert f.revisions == 1


def test_human_feedback_revises_and_pauses_again(fake):
    f = fake()
    graph = new_graph()
    runner.start(graph, INPUTS, "t5", CTX)

    snap = runner.resume(
        graph, {"action": "revise", "feedback": "Shorter cover letter please"}, "t5", CTX
    )
    review = runner.pending_review(snap)
    assert review is not None
    assert review["cover_letter_draft"] == "cover_letter v1"
    assert "Shorter cover letter please" in f.revision_feedback[0]
    assert snap.values["human_revisions"] == 1
    assert snap.values["human_feedback"] == ""

    snap = runner.resume(graph, {"action": "approve"}, "t5", CTX)
    assert snap.values["approved"] is True


def test_revise_without_feedback_counts_as_approve(fake):
    fake()
    graph = new_graph()
    runner.start(graph, INPUTS, "t6", CTX)
    snap = runner.resume(graph, {"action": "revise", "feedback": "   "}, "t6", CTX)
    assert snap.values["approved"] is True


def test_missing_job_raises(fake):
    fake()
    with pytest.raises(ValueError, match="job_text or job_url"):
        runner.start(new_graph(), {"resume_text": "x"}, "t7", CTX)
