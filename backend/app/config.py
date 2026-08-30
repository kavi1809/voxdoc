from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # ── Gemini ─────────────────────────────────────────────────────────────────
    gemini_api_key: str = ""

    # Model IDs live in config, never hardcoded in call sites: Google retires
    # Gemini models on a fast cadence (1.5 is already gone, 2.5 retires Oct 2026),
    # so swapping one should be a .env change, not a code change.
    chat_model: str = "gemini-3.6-flash"        # agent loop — needs tool calling
    summary_model: str = "gemini-3.5-flash-lite"  # cheap tier for doc summaries
    transcribe_model: str = "gemini-3.5-flash-lite"  # cheap tier for audio → text

    # ── Embeddings ─────────────────────────────────────────────────────────────
    # "local"  → fastembed / ONNX, runs on CPU, zero API calls, zero cost.
    # "gemini" → gemini-embedding-001 via the API (kept for comparison).
    embedding_provider: str = "local"
    local_embedding_model: str = "BAAI/bge-small-en-v1.5"  # 384-dim, ~130MB
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dim: int = 768  # MRL-truncated so both providers stay small

    # Where the local ONNX model is cached. Defaults to a folder next to the
    # data rather than the OS temp dir, which gets cleaned and forces re-downloads.
    model_cache_dir: str = "./model_cache"

    # ── App ────────────────────────────────────────────────────────────────────
    app_name: str = "Voxdoc"
    debug: bool = False
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # ── Storage ────────────────────────────────────────────────────────────────
    chroma_persist_dir: str = "./chroma_db"
    upload_dir: str = "./uploads"
    database_url: str = "sqlite:///./voxdoc.db"

    # ── Limits ─────────────────────────────────────────────────────────────────
    max_upload_mb: int = 25
    max_url_bytes: int = 5_000_000
    max_history_messages: int = 10   # how much chat history to feed the model
    agent_recursion_limit: int = 12  # caps a runaway tool loop
    pandas_timeout_seconds: int = 10

    # ── Auth ───────────────────────────────────────────────────────────────────
    secret_key: str = "change-this-in-production"
    access_token_expire_days: int = 7

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Settings are built once and reused — reading .env on every request is waste."""
    return Settings()
