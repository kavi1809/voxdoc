"""
Retrieval: local embeddings, hybrid fusion, and BM25 cache invalidation.

These run the real embedding model — it is local, free, and fast, and the point
of the tests is that no API call happens.
"""

import pytest

from app.services.hybrid_search import _tokenise, hybrid_search, invalidate
from app.services.vector_store import (
    delete_document_chunks,
    get_all_chunks,
    semantic_search,
    store_chunks,
)

CHUNKS = [
    "The company revenue declined sharply in Q3 due to supply chain disruption.",
    "Product SKU-4892 was discontinued in March following a safety recall.",
    "Employee headcount grew from 120 to 340 over the fiscal year.",
    "Our remote work policy allows three days working from home each week.",
]


@pytest.fixture
def indexed(app_client):
    """Index a small corpus into an isolated Chroma directory."""
    store_chunks("ws1", CHUNKS, "doc1")
    invalidate("ws1")
    yield "ws1"


def test_tokeniser_strips_punctuation():
    """`str.split()` left punctuation attached, so 'revenue.' never matched 'revenue'."""
    assert _tokenise("Revenue, declined. Sharply!") == ["revenue", "declined", "sharply"]
    assert "sku" in _tokenise("Product SKU-4892 recalled")


def test_semantic_search_matches_meaning_not_words(indexed):
    """'sales fell' shares no words with 'revenue declined' — only meaning."""
    results = semantic_search(indexed, "sales fell", top_k=1)
    assert results and "revenue declined" in results[0]


def test_hybrid_search_finds_exact_tokens(indexed):
    """The case BM25 exists for: an identifier embeddings tend to blur."""
    results = hybrid_search(indexed, "SKU-4892", top_k=2)
    assert any("SKU-4892" in chunk for chunk in results)


def test_hybrid_search_respects_top_k(indexed):
    assert len(hybrid_search(indexed, "policy", top_k=2)) <= 2


def test_search_on_an_empty_workspace_returns_nothing(app_client):
    assert hybrid_search("empty-ws", "anything", top_k=5) == []
    assert semantic_search("empty-ws", "anything", top_k=5) == []


def test_blank_query_returns_nothing(indexed):
    assert hybrid_search(indexed, "   ", top_k=5) == []


def test_bm25_cache_is_rebuilt_after_new_content(app_client):
    """
    The index is cached, so it must be invalidated when the corpus changes -
    otherwise newly uploaded documents stay invisible to keyword search.
    """
    store_chunks("ws2", ["Alpha document about budgets."], "docA")
    invalidate("ws2")
    assert len(hybrid_search("ws2", "budgets", top_k=5)) == 1

    store_chunks("ws2", ["Beta document mentioning SKU-1234 explicitly."], "docB")
    invalidate("ws2")

    results = hybrid_search("ws2", "SKU-1234", top_k=5)
    assert any("SKU-1234" in chunk for chunk in results)


def test_deleting_a_document_removes_its_chunks(app_client):
    store_chunks("ws3", CHUNKS, "docX")
    invalidate("ws3")
    assert len(get_all_chunks("ws3")) == len(CHUNKS)

    delete_document_chunks("ws3", "docX")
    invalidate("ws3")
    assert get_all_chunks("ws3") == []


def test_workspaces_are_isolated_from_each_other(app_client):
    store_chunks("wsA", ["Confidential salary information for executives."], "d1")
    store_chunks("wsB", ["Public marketing brochure text."], "d2")
    invalidate("wsA")
    invalidate("wsB")

    results = hybrid_search("wsB", "salary information", top_k=5)
    assert not any("Confidential" in chunk for chunk in results)


def test_embeddings_are_generated_locally(app_client, monkeypatch):
    """Guard the headline saving: indexing must not touch the Gemini API."""
    from app.services import gemini

    def explode(*args, **kwargs):
        raise AssertionError("An embedding call reached the Gemini API")

    monkeypatch.setattr(gemini, "get_client", explode)

    store_chunks("ws-local", CHUNKS, "doc-local")
    invalidate("ws-local")
    assert hybrid_search("ws-local", "remote work", top_k=1)
