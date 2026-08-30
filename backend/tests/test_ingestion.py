"""Chunking and SSRF protection."""

import pytest
from fastapi import HTTPException

from app.services.ingestion import _assert_public_url, chunk_text, describe_dataframe


def test_chunks_overlap_so_boundary_sentences_survive():
    words = [f"w{i}" for i in range(1000)]
    chunks = chunk_text(" ".join(words), chunk_size=100, overlap=20)

    assert len(chunks) > 1
    first = chunks[0].split()
    second = chunks[1].split()
    assert len(first) == 100
    # The last 20 words of chunk 1 must reappear at the start of chunk 2.
    assert first[-20:] == second[:20]


def test_short_text_is_a_single_chunk():
    assert chunk_text("just a few words here") == ["just a few words here"]


def test_empty_text_produces_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_no_infinite_loop_when_text_is_shorter_than_chunk_size():
    assert len(chunk_text("one two three", chunk_size=500, overlap=50)) == 1


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=50, overlap=50)


PRIVATE_URLS = [
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata service
    "http://127.0.0.1:8000/api/auth/me",         # this API itself
    "http://localhost/admin",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "http://[::1]/",
]


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_private_addresses_are_refused(url):
    with pytest.raises(HTTPException) as exc:
        _assert_public_url(url)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x/"])
def test_non_http_schemes_are_refused(url):
    with pytest.raises(HTTPException):
        _assert_public_url(url)


def test_describe_dataframe_reports_schema_not_data():
    import pandas as pd

    df = pd.DataFrame({"region": ["N", "S"], "sales": [10, 20]})
    described = describe_dataframe(df)

    assert "2 rows x 2 columns" in described
    assert "region" in described and "sales" in described
