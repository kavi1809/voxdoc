"""
Text → vector, with a swappable provider.

Default is `local`: fastembed runs BAAI/bge-small-en-v1.5 through ONNX Runtime on
the CPU. This is the single biggest API-call saving in the project — embedding a
document used to be one Gemini round-trip *per chunk*, so a 200-page PDF meant
hundreds of sequential API calls. Locally it is free, offline, and batched.

`gemini` is kept as an alternative so the two can be compared. Note the vectors
are NOT interchangeable: switching provider means re-embedding every document.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# HuggingFace's Xet storage backend (pulled in by the `hf-xet` package) downloads
# large files from transfer.xethub.hf.co, which many corporate proxies silently
# block — the small config/tokenizer files arrive but the .onnx weights hang at
# 0 bytes indefinitely. Forcing the classic CDN makes the download complete in
# seconds. setdefault, so an explicit environment value still wins.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# Keep the model out of the OS temp directory, which gets cleaned periodically
# and would trigger a fresh download. In Docker this path is a mounted volume.
if settings.model_cache_dir:
    os.environ.setdefault("FASTEMBED_CACHE_PATH", settings.model_cache_dir)


class EmbeddingProvider(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


# ── Local (fastembed / ONNX) ───────────────────────────────────────────────────


class LocalEmbedder:
    """
    Wraps fastembed. The model is loaded lazily on first use and then reused —
    loading is the expensive part (~1s), embedding is fast.

    bge models are asymmetric: queries need a prefix ("Represent this sentence
    for searching relevant passages: ") that passages do not. fastembed's
    `query_embed` applies the correct per-model prefix for us, so we call the
    right method for each side rather than hardcoding the string.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()
        self._dim: int | None = None

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:  # re-check inside the lock
                    from fastembed import TextEmbedding

                    logger.info("Loading local embedding model %s", self.model_name)
                    self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = len(self.embed_query("dimension probe"))
        return self._dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        return [vec.tolist() for vec in model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        model = self._get_model()
        return next(iter(model.query_embed(text))).tolist()


# ── Gemini ─────────────────────────────────────────────────────────────────────


def _normalise(vec: list[float]) -> list[float]:
    """MRL-truncated Gemini vectors are not unit length; cosine needs them to be."""
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


class GeminiEmbedder:
    """gemini-embedding-001. Kept for comparison against the local path."""

    # The API rejects oversized batches; 100 is comfortably within limits.
    BATCH_SIZE = 100

    def __init__(self, model_name: str, output_dim: int) -> None:
        self.model_name = model_name
        self._dim = output_dim

    @property
    def dim(self) -> int:
        return self._dim

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        from app.services.gemini import get_client

        client = get_client()
        out: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            resp = client.models.embed_content(
                model=self.model_name,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self._dim,
                ),
            )
            out.extend(_normalise(list(e.values)) for e in resp.embeddings)
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


# ── Selection ──────────────────────────────────────────────────────────────────

_provider: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        if settings.embedding_provider == "gemini":
            _provider = GeminiEmbedder(
                settings.gemini_embedding_model, settings.gemini_embedding_dim
            )
        else:
            _provider = LocalEmbedder(settings.local_embedding_model)
    return _provider


def embed_documents(texts: list[str]) -> list[list[float]]:
    return get_embedder().embed_documents(texts)


def embed_query(text: str) -> list[float]:
    return get_embedder().embed_query(text)
