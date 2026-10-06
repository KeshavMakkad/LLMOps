FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FRUGAL_ROOT=/app FRUGAL_CACHE_DIR=/tmp/frugal-cache \
    FASTEMBED_CACHE_PATH=/app/.fastembed FRUGAL_EMBED_CACHE=/app/.frugal/embeddings.sqlite
WORKDIR /app

COPY pyproject.toml README.md ./
COPY frugal ./frugal
RUN pip install --upgrade pip && pip install ".[tracing]"

COPY configs ./configs
COPY data ./data
COPY results ./results
# Bake the embedding + reranker models and the pre-embedded corpus/trace into the image, so the
# 512 MB instance only embeds short live questions at runtime and cold starts stay fast.
RUN frugal build-index

RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn frugal.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
