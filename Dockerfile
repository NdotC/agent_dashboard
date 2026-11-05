# syntax=docker/dockerfile:1

# ---- Frontend bauen ----
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx vite build

# ---- Laufzeit ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENTDASH_DATA_DIR=/data \
    AGENTDASH_STATIC_DIR=/app/static
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/agentdash_server backend/agentdash_server
RUN pip install ./backend && useradd --uid 1000 --create-home agentdash && mkdir -p /data && chown agentdash /data
COPY --from=frontend /src/dist /app/static
USER agentdash
VOLUME ["/data"]
# UI/API, OTLP/HTTP, Ollama-Proxy
EXPOSE 8080 4318 11434
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"
CMD ["agentdash-server"]
