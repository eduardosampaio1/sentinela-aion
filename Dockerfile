# ── Stage 1: Build dependencies ──
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# Copy only dependency definition first (layer caching)
COPY pyproject.toml README.md ./

# Install dependencies into a virtual env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .

# ── Stage 2: Production image ──
FROM python:3.11-slim AS production

WORKDIR /app

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY aion/ ./aion/
COPY config/ ./config/

# Non-root user
RUN useradd --create-home --shell /bin/bash aion
USER aion

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()"

CMD ["python", "-m", "aion.cli"]
