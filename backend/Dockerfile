FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=10000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp uses a JS runtime for YouTube signature solving. Deno is the recommended one.
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend
EXPOSE 10000

CMD ["sh", "-c", "gunicorn --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:${PORT:-10000} server:app"]
