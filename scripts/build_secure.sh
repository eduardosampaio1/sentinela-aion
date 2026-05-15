#!/bin/bash
# build_secure.sh — Compile Python sources to bytecode and strip .py files
# Usage: Run from the repository root before building the Docker image.
#
# This prevents reverse-engineering of the AION source code in production
# containers. The compiled .pyc files are functionally equivalent.
set -euo pipefail

AION_DIR="${1:-aion}"

if [ ! -d "$AION_DIR" ]; then
  echo "ERROR: $AION_DIR/ directory not found. Run from the repo root."
  exit 1
fi

echo "Step 1: Compiling Python sources to bytecode (.pyc)..."
python -m compileall -b -q "$AION_DIR" 2>&1 | grep -v "^Listing" || true

PYCOMPILED=$(find "$AION_DIR" -name "*.pyc" | wc -l)
echo "  Compiled $PYCOMPILED modules"

echo "Step 2: Removing .py source files..."
PYCOUNT=$(find "$AION_DIR" -name "*.py" -type f | wc -l)

if [ "$PYCOUNT" -eq 0 ]; then
  echo "  ERROR: No .py files found! Aborting."
  exit 1
fi

find "$AION_DIR" -name "*.py" -type f -delete
echo "  Deleted $PYCOUNT source files"

echo "Step 3: Verifying no .py files remain..."
REMAINING=$(find "$AION_DIR" -name "*.py" | wc -l)

if [ "$REMAINING" -gt 0 ]; then
  echo "  ERROR: $REMAINING .py files still present!"
  find "$AION_DIR" -name "*.py"
  exit 1
fi

echo "Step 4: Verifying .pyc files exist..."
FINAL_COUNT=$(find "$AION_DIR" -name "*.pyc" | wc -l)
if [ "$FINAL_COUNT" -lt 10 ]; then
  echo "  ERROR: Only $FINAL_COUNT .pyc files found (expected many more)"
  exit 1
fi

echo ""
echo "SUCCESS: $FINAL_COUNT bytecode files ready, 0 source files remain"
echo "Next: docker build -t aion:secure ."
