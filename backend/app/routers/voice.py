from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import get_settings
from app.db.models import User
from app.deps import get_current_user
from app.services.gemini import transcribe_audio

router = APIRouter()
settings = get_settings()

MAX_AUDIO_MB = 10
ALLOWED_AUDIO = {"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4", "audio/x-m4a"}


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """
    Speech to text, as a fallback only.

    The frontend prefers the browser's built-in SpeechRecognition, which is free
    and instant. This endpoint exists for browsers that lack it (mainly Firefox),
    so in practice it is rarely hit.
    """
    mime = (audio.content_type or "audio/webm").split(";")[0]
    if mime not in ALLOWED_AUDIO:
        raise HTTPException(400, f"Unsupported audio type: {mime}")

    data = await audio.read(MAX_AUDIO_MB * 1024 * 1024 + 1)
    if len(data) > MAX_AUDIO_MB * 1024 * 1024:
        raise HTTPException(413, f"Audio is larger than the {MAX_AUDIO_MB} MB limit")
    if not data:
        raise HTTPException(400, "Empty audio file")

    # Sent inline rather than via the Files API — the clip is a few seconds long,
    # so there is nothing to gain from an upload round-trip and a temp file.
    text = await transcribe_audio(data, mime)
    return {"text": text}
