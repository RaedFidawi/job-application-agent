"""Drives the Streamlit page headlessly through generate -> revise -> approve."""

from streamlit.testing.v1 import AppTest
from test_graph import FakeLLM

from job_agent import llm


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_full_flow(monkeypatch):
    monkeypatch.setattr(llm, "get_model", lambda ctx: FakeLLM([]))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    at = AppTest.from_file("../src/job_agent/web.py", default_timeout=30).run()
    at.text_area[0].input("We need a Python backend engineer.")
    at.text_area[1].input("Jane Doe, Python developer")
    _button(at, "Generate application").click().run()
    assert not at.exception
    assert any("Fit score: 80/100" in s.value for s in at.subheader)

    at.text_area[0].input("Shorter please")
    _button(at, "Request changes").click().run()
    assert any("cover_letter v1" in m.value for m in at.markdown)

    _button(at, "Approve").click().run()
    assert any("Approved" in s.value for s in at.success)
