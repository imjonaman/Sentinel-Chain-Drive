# Production-ready multi-stage / non-root Dockerfile for Sentinel Chain Drive
FROM python:3.13-slim AS runner

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install security updates and curl for container health check
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged service user and group
RUN groupadd -g 10001 sentinel \
    && useradd -u 10001 -g sentinel -s /bin/sh -m sentinel

# Install locked dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source and configuration
COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY src ./src

# Change ownership to unprivileged user
RUN chown -R sentinel:sentinel /app

# Switch to non-root execution context
USER sentinel

EXPOSE 8000

# Container healthcheck targeting liveness probe
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

CMD ["uvicorn", "sentinel_chain_drive.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
