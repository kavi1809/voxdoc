import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.db.session import init_db
from app.rate_limit import limiter
from app.routers import auth, chat, documents, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup work belongs here, not at import time."""
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.chroma_persist_dir, exist_ok=True)
    init_db()

    if not settings.debug and settings.secret_key == "change-this-in-production":
        raise RuntimeError(
            "SECRET_KEY is still the default value. Set a long random SECRET_KEY "
            "in .env before running with DEBUG=false."
        )
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set - chat and summaries will fail.")

    logger.info(
        "Voxdoc ready (embeddings=%s, chat_model=%s)",
        settings.embedding_provider,
        settings.chat_model,
    )
    yield


app = FastAPI(
    title="Voxdoc API",
    description="Voice-first intelligent document assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests, slow down."})


# The Vite dev server proxies /api, so in development this is belt-and-braces;
# it matters when the frontend is served from a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(voice.router, prefix="/api/voice", tags=["Voice"])


@app.get("/")
async def root():
    return {"message": "Voxdoc API is running", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}
