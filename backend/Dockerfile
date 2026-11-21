# AI ComicVerse backend.
#
# Slim by default: the heavy optional extras (torch/open_clip, chromadb,
# opencv, faster-whisper) are NOT installed, so the image builds in a minute and
# runs the pipeline with the built-in fallbacks. Uncomment the extras block to
# bake them in.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# PostgreSQL client libs (psycopg2, only needed for the extras block) plus the
# fonts Pillow needs to letter panels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        fonts-dejavu-core \
        fonts-liberation \
        libpq5 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- optional heavy extras -------------------------------------------------
# libpq-dev gcc libgl1 libglib2.0-0 ffmpeg are needed to build/run these.
# RUN apt-get update && apt-get install -y --no-install-recommends \
#         gcc libpq-dev libgl1 ffmpeg && rm -rf /var/lib/apt/lists/*
# COPY requirements-extras.txt ./
# RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
#  && pip install --no-cache-dir -r requirements-extras.txt

COPY . .

RUN mkdir -p storage/projects storage/refs storage/memory storage/tmp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
