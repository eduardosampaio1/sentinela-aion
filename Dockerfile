# AION — Production Docker image
#
# Four stages:
#   1. builder      — install Python deps (layer cached independently)
#   2. model-cache  — pre-download embedding model (~150 MB) into /opt/hf-model
#   3. obfuscator   — compile .py → .pyc and strip source files from the package
#   4. production   — slim non-root runtime; no .py sources in final layer
#
# Source protection (Fase 3):
#   The obfuscator stage compiles aion/ to bytecode and strips all .py files,
#   so the final image contains only .pyc bytecode. This prevents casual
#   inspection of the source tree and raises the bar for licence circumvention.
#   For stronger protection (PyArmor), use the tools/build_secure.sh script
#   outside Docker and COPY the obfuscated wheel instead of the source tree.
#
# Result: ~1.4 GB image, cold start < 10s (model already on disk).

# ── Stage 1: deps ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=0 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY aion/ ./aion/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip wheel setuptools && \
    pip install . && \
    pip install uvloop

# ── Stage 2: bundle embedding model ───────────────────────────────────────────
FROM builder AS model-cache

RUN python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download( \
    repo_id='sentence-transformers/all-MiniLM-L6-v2', \
    local_dir='/opt/hf-model', \
    local_dir_use_symlinks=False \
); \
print('model bundled at /opt/hf-model')"

# ── Stage 3: obfuscate — compile to .pyc and strip .py sources ────────────────
FROM builder AS obfuscator

# Compile the installed aion package to bytecode (optimization level 2 strips
# docstrings and assert statements in addition to normal .pyc generation).
RUN python -m compileall -b -j 0 -q /opt/venv/lib/python3.11/site-packages/aion/

# Strip all .py source files from the installed package, keeping only .pyc.
# The -exec rm is intentional — we want the final layer to have no .py sources.
RUN find /opt/venv/lib/python3.11/site-packages/aion/ -name "*.py" \
    ! -name "__init__.py" -delete
# Keep __init__.py files so Python package discovery still works,
# but remove their content (they are not needed at runtime once compiled).
RUN find /opt/venv/lib/python3.11/site-packages/aion/ -name "__init__.py" \
    -exec sh -c 'echo "" > "$1"' _ {} \;

# ── Stage 4: production runtime ───────────────────────────────────────────────
FROM python:3.11-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Embedding model served from disk — no HuggingFace download on boot
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    ESTIXE_EMBEDDING_MODEL=/opt/hf-model

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 aion \
    && mkdir -p /var/aion/runtime \
    && chown -R aion:aion /var/aion

# Obfuscated venv (no .py sources inside aion/ package)
COPY --from=obfuscator /opt/venv /opt/venv
COPY --from=model-cache /opt/hf-model /opt/hf-model

WORKDIR /app

# Config directory (models.yaml for NOMOS, etc.)
COPY config/ ./config/

RUN chown -R aion:aion /app

USER aion

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()"

CMD ["python", "-m", "aion.cli"]
