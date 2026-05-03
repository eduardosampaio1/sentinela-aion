"""AION Trust Guard — critical files registry (standalone, no aion imports).

Single source of truth for which files are covered by the integrity manifest.
Imported by:
  - aion/trust_guard/integrity_manifest.py (runtime verification)
  - tools/generate_manifest.py            (build-time hash generation)

Why standalone: the build-time tool runs in a CI environment where the AION
package may not be importable; this module only uses pathlib + glob and
must NEVER import from aion.* itself.

Coverage rationale (post qa-ceifador audit, P1.A):
  The previous registry covered only 7 files (license, middleware, pipeline,
  + 4 module entrypoints). Many sensitive files were outside the manifest
  and therefore mutable without tripping integrity verification. This list
  expands coverage to the full Python core that drives request handling,
  decisions, and security enforcement — without including operator-tunable
  YAMLs (which support hot-reload via /v1/estixe/intents/reload).

Categories:
  Tier A (BINARY core — Python source that ships in the image):
    every *.py under aion/ except __pycache__ and *_test.py.

  Tier B (operator configs — YAMLs that can be hot-reloaded):
    NOT included in this registry. Operators may legitimately edit
    config/*.yaml or aion/estixe/data/*.yaml at runtime; a future commit
    can introduce a separate "soft" manifest with weaker semantics.
"""

from __future__ import annotations

from pathlib import Path

# ── Tier A: Python core file patterns ──────────────────────────────────────────
# Globs are relative to the project root (folder containing the `aion/` package).
# Resolved by `resolve_files()` — supports three pattern shapes:
#   1. Literal file path (no glob char):    "aion/cli.py"
#   2. Single-level glob (one `*`):         "aion/cli.py" / "aion/routers/__*.py"
#   3. Recursive glob (`**`):               "aion/estixe/**/*.py"
#
# Codex pos-PR-10 review: the previous "aion/<module>/*.py" patterns missed
# nested files like aion/estixe/tools/seed_quality.py. We now use **/*.py for
# every module that has (or may have in the future) sub-packages.
CORE_FILE_PATTERNS: tuple[str, ...] = (
    # Top-level package — flat files
    "aion/__init__.py",
    "aion/cli.py",
    "aion/config.py",
    "aion/license.py",
    "aion/main.py",
    "aion/middleware.py",
    "aion/observability.py",
    "aion/pipeline.py",
    "aion/proxy.py",
    "aion/supabase_writer.py",
    # HTTP routers — entrypoints that handle every request
    "aion/routers/**/*.py",
    # Decision contract — emitted on every request, central to the audit story
    "aion/contract/**/*.py",
    # ESTIXE — block / bypass / policy / guardrails / risk / threat (+ tools/)
    "aion/estixe/**/*.py",
    # NOMOS — model registry, complexity classifier, cost calc, router
    "aion/nomos/**/*.py",
    # METIS — compressor, behavior dial, optimizer
    "aion/metis/**/*.py",
    # NEMOS — economics tracker, intent memory, baselines, recommendations
    "aion/nemos/**/*.py",
    # Shared core — schemas, RBAC contracts, budget store, telemetry, tokens
    "aion/shared/**/*.py",
    # Cache layer (semantic cache, vector store)
    "aion/cache/**/*.py",
    # Adapter layer (LLM connection abstraction)
    "aion/adapter/**/*.py",
    # Collective / marketplace / reports — feature surfaces
    "aion/collective/**/*.py",
    "aion/marketplace/**/*.py",
    "aion/reports/**/*.py",
    # Trust Guard internals (manifest verifier, license authority, etc.)
    "aion/trust_guard/**/*.py",
)

# Files that exist as glob matches but should NEVER be included in the manifest.
# Examples: __pycache__ (compiled), *_test.py (tests not shipped),
# integrity_manifest.json (the manifest itself).
EXCLUDE_PATTERNS: tuple[str, ...] = (
    "__pycache__",
    ".pyc",
    "_test.py",
    "test_",
    "/tests/",
)


def _is_excluded(rel_path: str) -> bool:
    """True if the relative path matches any exclusion pattern."""
    p = rel_path.replace("\\", "/")
    for pat in EXCLUDE_PATTERNS:
        if pat in p:
            return True
    return False


def resolve_files(root: Path) -> list[str]:
    """Resolve all CORE_FILE_PATTERNS into a sorted list of relative paths.

    Args:
        root: project root (the directory containing the `aion/` package).

    Returns:
        Sorted list of POSIX-style relative paths (e.g. "aion/routers/proxy.py").
        Each path corresponds to an existing file on disk; missing files are
        skipped (so a glob like "aion/marketplace/**/*.py" that has no matches
        contributes nothing rather than appearing as MISSING).

    Pattern shapes supported:
        - Literal file path:   "aion/cli.py"
        - Single-level glob:   "aion/routers/*.py"     (immediate children only)
        - Recursive glob:      "aion/estixe/**/*.py"   (all descendants)
    """
    root = Path(root)
    seen: set[str] = set()
    for pattern in CORE_FILE_PATTERNS:
        if "**" in pattern:
            # Recursive: "aion/estixe/**/*.py" → rglob("*.py") inside "aion/estixe".
            # We use rglob (not Path.glob with **) for explicit recursion semantics
            # across all supported Python versions and to avoid surprises if the
            # pattern ever evolves beyond a simple "**/<glob>" tail.
            prefix, _, tail = pattern.partition("/**/")
            base = root / prefix
            if not base.is_dir():
                continue
            for match in base.rglob(tail):
                if not match.is_file():
                    continue
                rel = str(match.relative_to(root)).replace("\\", "/")
                if _is_excluded(rel):
                    continue
                seen.add(rel)
        elif "*" in pattern:
            # Single level: "aion/routers/*.py" → glob "*.py" inside "aion/routers"
            prefix, _, glob = pattern.rpartition("/")
            base = root / prefix
            if not base.is_dir():
                continue
            for match in base.glob(glob):
                if not match.is_file():
                    continue
                rel = str(match.relative_to(root)).replace("\\", "/")
                if _is_excluded(rel):
                    continue
                seen.add(rel)
        else:
            # Literal file path
            full = root / pattern
            if full.is_file():
                rel = str(full.relative_to(root)).replace("\\", "/")
                if not _is_excluded(rel):
                    seen.add(rel)
    return sorted(seen)
