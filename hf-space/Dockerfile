FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# ffmpeg merges video+audio; curl/unzip install Deno, which yt-dlp needs for YouTube.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

# Hugging Face Docker Spaces run as UID 1000.
RUN useradd -m -u 1000 user

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY --chown=user:user backend ./backend
COPY --chown=user:user frontend ./frontend

ENV HOME=/home/user \
    XDG_CACHE_HOME=/tmp/cache \
    WORK_DIR=/tmp/kedao \
    TRUST_PROXY=1 \
    MAX_FILESIZE_MB=300 \
    MAX_DURATION_MIN=90 \
    MAX_ACTIVE_DOWNLOADS=2 \
    JOB_TTL_MIN=60 \
    PROBE_LIMIT=20 \
    DOWNLOAD_LIMIT=5 \
    RATE_WINDOW_MIN=10 \
    ALLOWED_ORIGINS=*

USER user
WORKDIR /app/backend
EXPOSE 7860

CMD ["gunicorn", "--workers", "1", "--threads", "8", "--timeout", "300", "--bind", "0.0.0.0:7860", "server:app"]
