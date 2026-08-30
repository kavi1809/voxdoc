"""
Hybrid retrieval: dense (semantic) + sparse (BM25), fused with Reciprocal Rank Fusion.

WHY HYBRID?
  Semantic search understands meaning — "revenue dropped" finds "sales declined" —
  but drifts on exact tokens like "SKU-4892" or "Section 4.2(b)".
  BM25 nails exact tokens but has no concept of synonyms.
  RRF combines their rankings, so a chunk that both methods like wins.

The BM25 index is CACHED. The previous version pulled the entire corpus out of
Chroma and rebuilt the index on *every single query* — O(corpus) work per
question. Now it is built once per workspace, kept in memory, persisted to disk,
and invalidated only when the workspace's documents actually change.
"""

from __future__ import annotations

import logging
import pickle
import re
import threading
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.services.vector_store import get_all_chunks, semantic_search

logger = logging.getLogger(__name__)
settings = get_settings()

# RRF's damping constant. 60 is the value from the original Cormack et al. paper
# and is what nearly every implementation uses; it stops rank-1 hits from
# completely dominating rank-2+.
RRF_K = 60

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_cache: dict[str, "_Index"] = {}
_lock = threading.Lock()


def _tokenise(text: str) -> list[str]:
    """
    Lowercase alphanumeric runs. `str.split()` (the old approach) left punctuation
    attached, so "revenue." and "revenue" were different terms and never matched.
    """
    return _TOKEN_RE.findall(text.lower())


class _Index:
    __slots__ = ("bm25", "chunks", "size")

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.size = len(chunks)
        self.bm25 = BM25Okapi([_tokenise(c) for c in chunks]) if chunks else None


def _cache_path(workspace_id: str) -> Path:
    d = Path(settings.chroma_persist_dir) / "bm25"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{workspace_id}.pkl"


def invalidate(workspace_id: str) -> None:
    """Called whenever a workspace's documents change."""
    with _lock:
        _cache.pop(workspace_id, None)
    path = _cache_path(workspace_id)
    if path.exists():
        try:
            path.unlink()
        except OSError as exc:
            logger.debug("Could not remove BM25 cache %s: %s", path, exc)


def _load_index(workspace_id: str) -> _Index | None:
    cached = _cache.get(workspace_id)
    if cached is not None:
        return cached

    path = _cache_path(workspace_id)
    if path.exists():
        try:
            with path.open("rb") as fh:
                index = pickle.load(fh)
            # Only trust the disk cache if it still matches the live corpus size.
            if isinstance(index, _Index) and index.size == len(get_all_chunks(workspace_id)):
                with _lock:
                    _cache[workspace_id] = index
                return index
        except Exception as exc:
            logger.debug("Ignoring unreadable BM25 cache %s: %s", path, exc)

    chunks = get_all_chunks(workspace_id)
    if not chunks:
        return None

    index = _Index(chunks)
    with _lock:
        _cache[workspace_id] = index
    try:
        with path.open("wb") as fh:
            pickle.dump(index, fh)
    except Exception as exc:
        logger.debug("Could not persist BM25 cache %s: %s", path, exc)
    return index


def hybrid_search(workspace_id: str, query: str, top_k: int = 5) -> list[str]:
    """Return the top_k most relevant chunks for a query."""
    if not query.strip():
        return []

    # Pull a wider candidate pool from each retriever than we intend to return.
    # RRF only earns its keep when the two lists have room to disagree.
    pool = max(top_k * 3, 10)

    semantic_results = semantic_search(workspace_id, query, top_k=pool)

    index = _load_index(workspace_id)
    if index is None or index.bm25 is None:
        return semantic_results[:top_k]

    scores = index.bm25.get_scores(_tokenise(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    bm25_results = [index.chunks[i] for i in ranked[:pool] if scores[i] > 0]

    # Reciprocal Rank Fusion: score = sum over lists of 1/(rank + K).
    rrf: dict[str, float] = {}
    for rank, chunk in enumerate(semantic_results):
        rrf[chunk] = rrf.get(chunk, 0.0) + 1.0 / (rank + RRF_K)
    for rank, chunk in enumerate(bm25_results):
        rrf[chunk] = rrf.get(chunk, 0.0) + 1.0 / (rank + RRF_K)

    merged = sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)
    return [chunk for chunk, _ in merged[:top_k]]
