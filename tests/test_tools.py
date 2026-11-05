import httpx
import pytest

from job_agent import tools


def test_html_to_text_strips_chrome():
    html = """<html><head><script>var x=1</script><style>p{}</style></head>
    <body><nav>Home | Jobs</nav><h1>Backend Engineer</h1><p>Build   APIs</p>
    <footer>© Acme</footer></body></html>"""
    text = tools.html_to_text(html)
    assert "Backend Engineer" in text
    assert "Build   APIs" in text
    assert "var x" not in text and "Home | Jobs" not in text and "Acme" not in text


def _mock_get(monkeypatch, status: int, body: str):
    def fake_get(url, **kw):
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(tools.httpx, "get", fake_get)


def test_fetch_rejects_blocked_sites(monkeypatch):
    _mock_get(monkeypatch, 403, "Forbidden")
    with pytest.raises(tools.JobFetchError, match="paste the job description"):
        tools.fetch_job_posting("https://example.com/job")


def test_fetch_rejects_js_only_pages(monkeypatch):
    _mock_get(monkeypatch, 200, "<html><body><div id=root></div></body></html>")
    with pytest.raises(tools.JobFetchError, match="JavaScript"):
        tools.fetch_job_posting("https://example.com/job")


def test_fetch_server_errors_are_raised_for_retry(monkeypatch):
    _mock_get(monkeypatch, 503, "down")
    with pytest.raises(httpx.HTTPStatusError):
        tools.fetch_job_posting("https://example.com/job")


def test_read_resume_text():
    assert tools.read_resume_bytes(b"  Jane Doe\nEngineer ", "cv.md") == "Jane Doe\nEngineer"


def test_read_resume_empty_raises():
    with pytest.raises(ValueError):
        tools.read_resume_bytes(b"   ", "cv.txt")
