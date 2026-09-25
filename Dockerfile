# ── Stage 1 : build du frontend React ─────────────────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2 : backend Python + Chromium + écran virtuel ───────────────────────
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DISPLAY=:99 \
    DATA_DIR=/data \
    ENV_PATH=/data/.env \
    APOLLO_COOKIES_PATH=/data/apollo_cookies.json \
    OUTPUT_DIR=/data/output

# Xvfb = écran virtuel (Apollo exige un navigateur non headless)
# x11vnc + noVNC = permet de voir/piloter ce navigateur depuis http://localhost:6080
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc novnc websockify fluxbox tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh

EXPOSE 8000 6080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
