# StockTrader Backend — Production Dockerfile
# Backend-only image (no Angular build stage).
# Use this for Fly.io / cloud deploys where the frontend is on Vercel.
#
#   docker build -f backend/Dockerfile -t stocktrader-api .
#   docker run -p 8000:8000 --env-file .env stocktrader-api

FROM python:3.13-slim

WORKDIR /app

# System deps for LightGBM / XGBoost runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Python deps (cached layer — only invalidated when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY backend/ ./backend/
COPY models/registry.json ./models/registry.json

# CSV market data for replay / demo mode
COPY storage/raw/ ./storage/raw/

# Non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# Health check (PORT defaults to 8000; overridden by $PORT at runtime)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/v1/health || exit 1

EXPOSE 8000

# Use shell form so $PORT is expanded at runtime (Fly.io sets PORT=8080)
CMD uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
