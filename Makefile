# AION — Makefile
# ============================================================
# Targets agrupados por audiência:
#
#   Cliente / POC:
#     make verify-poc           full smoke + assertions on a running stack
#     make verify-poc-decision  same, scoped to POC Decision-Only
#     make verify-poc-transparent  same, scoped to POC Transparent
#
#   Dev:
#     make test                 full pytest suite (slow + embeddings)
#     make test-fast            unit-only (no embeddings, no docker, no llm)
#     make test-poc             smoke set focused on POC enforcement
#     make manifest             generate aion/trust_guard/integrity_manifest.json
#     make help                 list targets
# ============================================================

PYTHON ?= python
PYTEST ?= $(PYTHON) -m pytest
COMPOSE ?= docker compose
BASE_URL ?= http://localhost:8080

.PHONY: help test test-fast test-poc verify-poc verify-poc-decision verify-poc-transparent manifest clean

help:
	@echo "AION targets:"
	@echo "  make verify-poc                 — smoke test against a running POC stack ($(BASE_URL))"
	@echo "  make verify-poc-decision        — POC Decision-Only specific assertions"
	@echo "  make verify-poc-transparent     — POC Transparent specific assertions"
	@echo "  make test                       — full pytest suite (slow + embeddings)"
	@echo "  make test-fast                  — pytest -m 'not slow and not requires_embeddings and not requires_docker and not requires_llm'"
	@echo "  make test-poc                   — only POC-related regression tests"
	@echo "  make manifest                   — regenerate Trust Guard integrity manifest"

# ── Tests ────────────────────────────────────────────────────────────────────

test:
	$(PYTEST) tests/

test-fast:
	$(PYTEST) tests/ -m "not slow and not requires_embeddings and not requires_docker and not requires_llm"

test-poc:
	$(PYTEST) tests/test_qa_ceifador_fixes.py -v

# ── POC verification scripts ─────────────────────────────────────────────────

verify-poc: verify-poc-decision
	@echo
	@echo "verify-poc OK"

verify-poc-decision:
	@./scripts/smoke-test.sh decision $(BASE_URL)

verify-poc-transparent:
	@./scripts/smoke-test.sh transparent $(BASE_URL)

# ── Trust Guard manifest ─────────────────────────────────────────────────────

manifest:
	$(PYTHON) tools/generate_manifest.py \
	  --out aion/trust_guard/integrity_manifest.json \
	  $(if $(SENTINELA_ARTIFACT_SIGNING_KEY_PATH),--artifact-key $(SENTINELA_ARTIFACT_SIGNING_KEY_PATH),)

clean:
	rm -rf .pytest_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
