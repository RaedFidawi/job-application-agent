"""Command-line client.

    job-agent --job https://... --resume resume.pdf
    job-agent --job-file posting.txt --resume resume.md --out applications/acme
    job-agent --thread <id>        # pick up a paused or crashed run
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver

from job_agent import runner
from job_agent.graph import build_graph
from job_agent.state import AgentContext
from job_agent.tools import read_resume_file

DEFAULT_DB = Path.home() / ".job_agent" / "checkpoints.sqlite"


def _print_fit(fit: dict) -> None:
    print(f"\n=== Fit: {fit['score']}/100 ===\n{fit['verdict']}\n")
    if fit["strengths"]:
        print("Strengths:")
        for s in fit["strengths"]:
            print(f"  + {s['requirement']}: {s['evidence']}")
    if fit["gaps"]:
        print("Gaps:")
        for g in fit["gaps"]:
            print(f"  - {g}")
    print(f"\nPositioning: {fit['positioning']}\n")


def _write_drafts(out: Path, review: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "resume.md").write_text(review["resume_draft"] + "\n")
    (out / "cover_letter.md").write_text(review["cover_letter_draft"] + "\n")


def _ask_decision() -> dict:
    print("Press Enter to approve, or type what to change (end with an empty line):")
    lines = []
    while True:
        try:
            line = input("> " if not lines else "  ")
        except EOFError:
            break
        if not line:
            break
        lines.append(line)
    if not lines:
        return {"action": "approve"}
    return {"action": "revise", "feedback": "\n".join(lines)}


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="Tailor your resume and cover letter to a job.")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--job", help="URL of the job posting")
    src.add_argument("--job-file", help="Text file containing the job description")
    p.add_argument("--resume", help="Your resume (.pdf, .md or .txt)")
    p.add_argument("--out", default="application", help="Output directory (default: ./application)")
    p.add_argument("--thread", help="Resume an existing run by thread id")
    p.add_argument("--model", default=os.getenv("JOB_AGENT_MODEL", "claude-opus-5-5"))
    p.add_argument("--effort", default=os.getenv("JOB_AGENT_EFFORT", "medium"),
                   choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--db", default=str(DEFAULT_DB), help="Checkpoint database path")
    args = p.parse_args(argv)

    if not args.thread and not (args.resume and (args.job or args.job_file)):
        p.error("provide --resume and one of --job/--job-file, or --thread to resume a run")

    ctx = AgentContext(model=args.model, effort=args.effort)
    out = Path(args.out)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    def on_step(node: str) -> None:
        print(f"  ✓ {runner.STEP_LABELS[node]}")

    with SqliteSaver.from_conn_string(args.db) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)

        if args.thread:
            thread_id = args.thread
            snap = graph.get_state({"configurable": {"thread_id": thread_id}})
            if not snap.values:
                print(f"No run found with thread id {thread_id}", file=sys.stderr)
                return 1
            if snap.next and not snap.interrupts:
                print(f"Continuing interrupted run {thread_id}…")
                snap = runner.continue_after_crash(graph, thread_id, ctx, on_step)
        else:
            thread_id = uuid.uuid4().hex[:12]
            inputs = {"resume_text": read_resume_file(args.resume)}
            if args.job:
                inputs["job_url"] = args.job
            else:
                inputs["job_text"] = Path(args.job_file).read_text()
            print(f"Run id: {thread_id}  (resume later with: job-agent --thread {thread_id})")
            snap = runner.start(graph, inputs, thread_id, ctx, on_step)

        first = True
        while (review := runner.pending_review(snap)) is not None:
            if first:
                _print_fit(review["fit"])
                first = False
            _write_drafts(out, review)
            print(f"Drafts written to {out}/resume.md and {out}/cover_letter.md")
            if not review["fact_check"]["passed"]:
                print("\n⚠ The fact-checker still has concerns:")
                for issue in review["fact_check"]["issues"]:
                    print(f"  - {issue}")
            print()
            snap = runner.resume(graph, _ask_decision(), thread_id, ctx, on_step)

        if snap.values.get("approved"):
            print(f"\nApproved. Final documents are in {out}/")
            return 0
        print("Run ended without approval.", file=sys.stderr)
        return 1


def web() -> None:
    """Entry point for `job-agent-web`: launch the Streamlit UI."""
    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", str(Path(__file__).with_name("web.py")), *sys.argv[1:]]
    sys.exit(stcli.main())


if __name__ == "__main__":
    sys.exit(main())
