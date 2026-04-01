# =============================================================================
# Multi-stage Dockerfile — NBFC Compliance AI (ECS Fargate)
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: builder — compile wheels & install deps into /install
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime — lean image with only what the app needs
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN groupadd --gid 1001 appuser && \
    useradd  --uid 1001 --gid 1001 --no-create-home --shell /sbin/nologin appuser

WORKDIR /app

COPY . /app

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8000/health"]

USER appuser

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-config", "/dev/null"]
