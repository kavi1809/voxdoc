"""
Chroma vector store.

Each workspace gets its own collection, so documents from one workspace can never
surface in another — the isolation is structural, not a filter we might forget.
"""

from __future__ import annotations

import logging

import chromadb

from app.config import get_settings
from app.services.embeddings import embed_documents, embed_query, get_embedder

logger = logging.getLogger(__name__)
settings = get_settings()

_client: chromadb.ClientAPI | None = None


def get_client() -> chromadb.ClientAPI:
    """Persistent client — data survives restarts."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _client


def collection_name(workspace_id: str) -> str:
    return f"workspace_{workspace_id}"


def get_collection(workspace_id: str):
    """
    embedding_function=None is deliberate: we always pass vectors in ourselves.
    Leaving it unset makes Chroma load its own ONNX MiniLM model, which would
    both waste memory and silently embed queries with a *different* model than
    the documents were stored with.
    """
    return get_client().get_or_create_collection(
        name=collection_name(workspace_id),
        embedding_function=None,
        metadata={"hnsw:space": "cosine"},
    )


def _check_dimension(collection) -> None:
    """
    Guard against the classic embedding-model-swap corruption: if the collection
    already holds vectors of a different width than the current model produces,
    every similarity score becomes meaningless (or Chroma errors deep in a query).
    Fail loudly and early with an actionable message instead.
    """
    if collection.count() == 0:
        return
    peek = collection.peek(limit=1)
    stored = peek.get("embeddings")
    if stored is None or len(stored) == 0:
        return
    stored_dim = len(stored[0])
    current_dim = get_embedder().dim
    if stored_dim != current_dim:
        raise RuntimeError(
            f"Embedding dimension mismatch in '{collection.name}': stored vectors are "
            f"{stored_dim}-d but the current provider "
            f"({settings.embedding_provider}) produces {current_dim}-d. "
            f"Delete '{settings.chroma_persist_dir}' and re-upload the documents "
            f"after changing embedding models."
        )


def store_chunks(workspace_id: str, chunks: list[str], doc_id: str) -> int:
    """Embed and store a document's chunks. Returns how many were stored."""
    if not chunks:
        return 0

    collection = get_collection(workspace_id)
    _check_dimension(collection)

    # Batched in one call — the old code embedded one chunk at a time.
    embeddings = embed_documents(chunks)

    collection.add(
        ids=[f"{doc_id}_chunk_{i}" for i in range(len(chunks))],
        embeddings=embeddings,
        documents=chunks,
        metadatas=[{"doc_id": doc_id, "chunk_index": i} for i in range(len(chunks))],
    )
    return len(chunks)


def semantic_search(workspace_id: str, query: str, top_k: int = 5) -> list[str]:
    """Nearest chunks by cosine similarity."""
    collection = get_collection(workspace_id)
    total = collection.count()
    if total == 0:
        return []
    _check_dimension(collection)

    results = collection.query(
        query_embeddings=[embed_query(query)],
        n_results=min(top_k, total),
    )
    docs = results.get("documents") or []
    return docs[0] if docs else []


def get_all_chunks(workspace_id: str) -> list[str]:
    """Full corpus for a workspace — used to build the BM25 index."""
    collection = get_collection(workspace_id)
    if collection.count() == 0:
        return []
    return collection.get(include=["documents"]).get("documents") or []


def delete_document_chunks(workspace_id: str, doc_id: str) -> None:
    get_collection(workspace_id).delete(where={"doc_id": doc_id})


def delete_workspace_collection(workspace_id: str) -> None:
    try:
        get_client().delete_collection(name=collection_name(workspace_id))
    except Exception as exc:  # already gone is fine
        logger.debug("Collection delete skipped for %s: %s", workspace_id, exc)
