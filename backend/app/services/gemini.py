"""
Gemini client, on the current `google-genai` SDK.

The previous implementation used `google-generativeai`, which reached end of life
on 2025-11-30, and called `gemini-1.5-flash`/`-pro`, both of which are retired.
`google-genai` is client-based rather than model-object-based and, importantly,
exposes real async methods under `client.aio` — the old code declared functions
`async` but called blocking methods inside them, which stalled the event loop for
the whole server on every request.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import HTTPException

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SUMMARY_PROMPT = (
    "Summarise the following document in 3-4 sentences. "
    "Cover what it is about, its key topics, and any important data or conclusions. "
    "Reply with the summary only.\n\nDocument:\n"
)


@lru_cache
def get_client():
    """One client for the process. Raises if no API key is configured."""
    from google import genai

    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY is not configured on the server.",
        )
    return genai.Client(api_key=settings.gemini_api_key)


async def generate_summary(text: str) -> str:
    """
    One-off document summary, generated at upload time and stored in the DB, so
    it costs exactly one API call per document for the lifetime of that document.
    Runs on the cheap model tier and caps its input.
    """
    if not text.strip():
        return "This document appears to be empty or contains no extractable text."

    try:
        client = get_client()
        response = await client.aio.models.generate_content(
            model=settings.summary_model,
            contents=SUMMARY_PROMPT + text[:8000],
        )
        return (response.text or "").strip() or "No summary could be generated."
    except HTTPException:
        raise
    except Exception as exc:
        # A summary is a nice-to-have; never fail the whole upload over it.
        logger.warning("Summary generation failed: %s", exc)
        return "Summary unavailable (the model could not be reached)."


async def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """Speech → text. Only used when the browser has no native SpeechRecognition."""
    from google.genai import types

    try:
        client = get_client()
        response = await client.aio.models.generate_content(
            model=settings.transcribe_model,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                "Transcribe this audio exactly as spoken. "
                "Return only the transcription, with no commentary.",
            ],
        )
        return (response.text or "").strip()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        raise HTTPException(status_code=502, detail="Transcription failed") from exc
