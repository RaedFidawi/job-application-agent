"""Non-LLM steps: fetching job postings and reading resumes."""

from __future__ import annotations

import io
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
MIN_JOB_TEXT_CHARS = 300


class JobFetchError(Exception):
    """The posting couldn't be fetched or had no readable text."""


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = (line.strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line for line in lines if line))


def fetch_job_posting(url: str, timeout: float = 20.0) -> str:
    try:
        resp = httpx.get(
            url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        # 4xx won't fix itself on retry; surface it so the user can paste the text.
        if e.response.status_code < 500:
            raise JobFetchError(
                f"{url} returned HTTP {e.response.status_code}. Some sites (e.g. LinkedIn) "
                "block automated access; paste the job description text instead."
            ) from e
        raise

    text = html_to_text(resp.text)
    if len(text) < MIN_JOB_TEXT_CHARS:
        raise JobFetchError(
            f"Only found {len(text)} characters of text at {url}. The page is probably "
            "rendered with JavaScript; paste the job description text instead."
        )
    return text


def read_resume_bytes(data: bytes, filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        text = data.decode("utf-8", errors="replace")
    text = text.strip()
    if not text:
        raise ValueError(
            f"No text could be extracted from {filename}. If it's a scanned PDF, "
            "export it as text or Markdown instead."
        )
    return text


def read_resume_file(path: str | Path) -> str:
    path = Path(path)
    return read_resume_bytes(path.read_bytes(), path.name)
