# Rockstar Radar — multi-tenant platform (FastAPI + React SPA).
# Stage 1 builds the SPA; stage 2 runs the API which serves the built SPA from web/dist.

# ---- stage 1: build the React SPA ----
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# PostHog analytics key is a PUBLIC ingest key — safe to inline at build. Empty = analytics off.
ARG VITE_POSTHOG_KEY=""
ARG VITE_POSTHOG_HOST="/ingest"
ENV VITE_POSTHOG_KEY=$VITE_POSTHOG_KEY VITE_POSTHOG_HOST=$VITE_POSTHOG_HOST
RUN npm run build          # -> /web/dist

# ---- stage 2: Python API ----
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8080
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# App code (data/ and secrets are excluded via .dockerignore; provided at runtime by a volume + env).
COPY . .
# Ship the freshly built SPA from stage 1 (overrides anything copied above).
COPY --from=web /web/dist ./web/dist

EXPOSE 8080
# Multi-tenant platform entrypoint. Real mode by default (users connect their own broker);
# the market-open scheduler runs inside this process.
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
