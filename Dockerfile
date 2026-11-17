# syntax=docker/dockerfile:1
# AURORA LOGISTICS AI — imagen única: frontend compilado + API + migraciones.
# El resultado sirve la aplicación completa en el puerto 8000.

# ---------- 1. Compilación del frontend ----------
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Sin NEXT_PUBLIC_API_BASE: en producción frontend y API comparten origen.
RUN npm run build

# ---------- 2. Backend y aplicación final ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Madrid

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system aurora \
    && adduser --system --ingroup aurora --home /app aurora

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY --from=frontend /build/frontend/out frontend/out

RUN mkdir -p /app/backend/data/storage \
    && chown -R aurora:aurora /app

USER aurora
WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
