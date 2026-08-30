FROM python:3.14-slim

# HuggingFace's Xet transfer backend is blocked by many corporate proxies, which
# makes the model download hang at 0 bytes. Force the classic CDN.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_DISABLE_XET=1 \
    FASTEMBED_CACHE_PATH=/app/model_cache

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Bake the embedding model into the image. Without this the first upload after
# every container start pays a ~130 MB download, and an air-gapped deployment
# would never work at all.
RUN python -c "\
import os; os.environ['HF_HUB_DISABLE_XET']='1'; \
from fastembed import TextEmbedding; \
TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/model_cache')"

# Writable data directories, owned by the unprivileged user the app runs as.
RUN mkdir -p /app/uploads /app/chroma_db \
    && useradd --create-home --uid 10001 voxdoc \
    && chown -R voxdoc:voxdoc /app
USER voxdoc

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
