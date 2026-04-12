# ── Stage 1: Build ──
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# Copy source + metadata, then install (complete package, not hollow)
COPY pyproject.toml README.md ./
COPY aion/ ./aion/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .

# ── Stage 2: Production ──
FROM python:3.11-slim AS production

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only config (aion/ is installed in venv)
COPY config/ ./config/

RUN useradd --create-home --shell /bin/bash aion
USER aion

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()"

CMD ["python", "-m", "aion.cli"]
