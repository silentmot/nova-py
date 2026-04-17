# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------
# Build stage — resolve and build wheels for pinned deps.
# ---------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Build deps needed by PyNaCl / aiohttp wheels on slim images.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libffi-dev libsodium-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN pip wheel --wheel-dir /wheels -r requirements.txt \
 && pip wheel --wheel-dir /wheels .

# ---------------------------------------------------------------------
# Runtime stage — minimal image with ffmpeg for voice playback.
# ---------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg is required by the /music cog to stream audio.
# libsodium provides runtime crypto for PyNaCl voice.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsodium23 ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash nova
WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels nova \
 && rm -rf /wheels

USER nova

# tini reaps zombies from ffmpeg/yt-dlp subprocesses.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "nova"]
