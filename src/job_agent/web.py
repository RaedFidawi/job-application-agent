"""Web UI. Launch with `job-agent-web` (or `streamlit run src/job_agent/web.py`).

Each browser session gets its own LangGraph thread. The graph pauses at
human_review; this page renders the pause payload and resumes the graph with
the user's decision.
"""

from __future__ import annotations

import os
import uuid

import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from job_agent import runner
from job_agent.graph import build_graph
from job_agent.state import AgentContext
from job_agent.tools import JobFetchError, read_resume_bytes

load_dotenv()
st.set_page_config(page_title="Job Application Agent", page_icon="📄", layout="wide")

MODELS = {
    "Claude Opus 5.5 (best quality)": "claude-opus-5-5",
    "Claude Sonnet 5.5 (cheaper)": "claude-sonnet-5-5",
    "Claude Haiku 5.5 (cheapest)": "claude-haiku-5-5",
}


@st.cache_resource
def get_graph():
    # One in-memory checkpointer shared by all sessions, keyed by thread id.
    # Fine for a demo; use Postgres/SQLite for durability across restarts.
    return build_graph(checkpointer=InMemorySaver())


graph = get_graph()
ss = st.session_state
ss.setdefault("thread_id", None)
ss.setdefault("review", None)
ss.setdefault("final", None)


def reset() -> None:
    ss.thread_id, ss.review, ss.final = None, None, None


# --- Sidebar: settings ------------------------------------------------------

with st.sidebar:
    st.header("Settings")
    env_key = os.getenv("ANTHROPIC_API_KEY")
    api_key = st.text_input(
        "Anthropic API key",
        type="password",
        placeholder="Using key from environment" if env_key else "sk-ant-…",
        help="Used only for this session and never stored. Get one at console.anthropic.com.",
    ) or env_key
    model = MODELS[st.selectbox("Model", list(MODELS))]
    effort = st.select_slider("Effort", ["low", "medium", "high"], value="medium")
    st.caption("Your resume and the job posting are sent to Anthropic's API to generate drafts.")
    if ss.thread_id:
        st.button("Start over", on_click=reset)

ctx = AgentContext(anthropic_api_key=api_key, model=model, effort=effort)

st.title("📄 Job Application Agent")
st.write(
    "Paste a job posting and upload your resume. The agent analyses the role, scores your fit, "
    "tailors your resume, writes a cover letter, fact-checks both against your real experience, "
    "and then waits for your review."
)


def run_with_progress(fn, *args) -> None:
    with st.status("Working…", expanded=True) as status:
        snap = fn(graph, *args, ctx, lambda node: st.write(f"✓ {runner.STEP_LABELS[node]}"))
        status.update(label="Done", state="complete", expanded=False)
    ss.review = runner.pending_review(snap)
    if snap.values.get("approved"):
        ss.final = snap.values


# --- Step 1: inputs ---------------------------------------------------------

if ss.thread_id is None:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1. The job")
        job_url = st.text_input("Job posting URL")
        job_text = st.text_area(
            "…or paste the job description", height=260,
            help="Use this for sites like LinkedIn that block automated access.",
        )
    with col2:
        st.subheader("2. Your resume")
        upload = st.file_uploader("Upload (.pdf, .md, .txt)", type=["pdf", "md", "txt"])
        resume_paste = st.text_area("…or paste it", height=180)

    if st.button("Generate application", type="primary"):
        if not api_key:
            st.error("Add your Anthropic API key in the sidebar.")
            st.stop()
        if not (job_url.strip() or job_text.strip()):
            st.error("Provide a job URL or paste the job description.")
            st.stop()
        try:
            resume_text = (
                read_resume_bytes(upload.getvalue(), upload.name) if upload else resume_paste.strip()
            )
        except ValueError as e:
            st.error(str(e))
            st.stop()
        if not resume_text:
            st.error("Upload or paste your resume.")
            st.stop()

        inputs = {"resume_text": resume_text}
        if job_text.strip():
            inputs["job_text"] = job_text.strip()
        else:
            inputs["job_url"] = job_url.strip()

        ss.thread_id = uuid.uuid4().hex
        try:
            run_with_progress(runner.start, inputs, ss.thread_id)
        except JobFetchError as e:
            reset()
            st.error(str(e))
            st.stop()
        st.rerun()

# --- Step 2: review loop ----------------------------------------------------

elif ss.review is not None:
    review = ss.review
    fit = review["fit"]

    st.subheader(f"Fit score: {fit['score']}/100")
    st.write(fit["verdict"])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Strengths**")
        for s in fit["strengths"]:
            st.markdown(f"- **{s['requirement']}**: {s['evidence']}")
    with c2:
        st.markdown("**Gaps**")
        for g in fit["gaps"] or ["None found"]:
            st.markdown(f"- {g}")
    st.info(f"**Positioning:** {fit['positioning']}")

    if not review["fact_check"]["passed"]:
        st.warning(
            "The fact-checker still flags these claims. Ask for changes if they're wrong:\n\n"
            + "\n".join(f"- {i}" for i in review["fact_check"]["issues"])
        )

    tab1, tab2 = st.tabs(["Tailored resume", "Cover letter"])
    with tab1:
        st.markdown(review["resume_draft"])
    with tab2:
        st.markdown(review["cover_letter_draft"])

    # A form submits the feedback text together with whichever button was clicked.
    with st.form("review_form"):
        feedback = st.text_area(
            "Want changes?",
            placeholder="e.g. Make the cover letter less formal and mention my open-source work.",
        )
        b1, b2 = st.columns([1, 5])
        approve = b1.form_submit_button("Approve", type="primary")
        request = b2.form_submit_button("Request changes")

    if approve:
        run_with_progress(runner.resume, {"action": "approve"}, ss.thread_id)
        st.rerun()
    if request:
        if not feedback.strip():
            st.error("Describe what you'd like changed, or click Approve.")
        else:
            run_with_progress(runner.resume, {"action": "revise", "feedback": feedback}, ss.thread_id)
            st.rerun()

# --- Step 3: done -----------------------------------------------------------

elif ss.final is not None:
    st.success("Approved. Download your documents below.")
    company = ss.final["job"]["company"].replace(" ", "_")
    d1, d2 = st.columns(2)
    d1.download_button("Download resume (.md)", ss.final["resume_draft"], f"resume_{company}.md")
    d2.download_button(
        "Download cover letter (.md)", ss.final["cover_letter_draft"], f"cover_letter_{company}.md"
    )
    tab1, tab2 = st.tabs(["Resume", "Cover letter"])
    tab1.markdown(ss.final["resume_draft"])
    tab2.markdown(ss.final["cover_letter_draft"])
