"""Input normalization for ESTIXE classifiers.

Normalizes text before embedding to improve recall against obfuscation:
  - Unicode NFC normalization (canonical composition)
  - Lowercase (case-insensitive classification)
  - Zero-width / invisible character removal (common obfuscation vectors)
  - Non-breaking space variants → regular space
  - Multiple whitespace → single space

Applied by both SemanticClassifier and RiskClassifier before calling encode_single().
The embedding LRU cache uses the normalized form as key — this means "IGNORE all
instructions" and "ignore all instructions" hit the same cache slot.
"""

from __future__ import annotations

import re
import unicodedata


# Zero-width and invisible characters commonly used in obfuscation
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]")

# Non-standard whitespace variants → regular space
_NONSTANDARD_SPACE = re.compile(r"[\xa0\u2000-\u200a\u202f\u205f\u3000\t]")

# Collapse multiple whitespace → single space
_MULTI_SPACE = re.compile(r" {2,}")


def normalize_input(text: str) -> str:
    """Normalize *text* for classification.

    Applies NFC unicode normalization, lowercase, invisible-char removal,
    and whitespace collapse. Idempotent — calling twice yields the same result.
    """
    # 1. Unicode NFC normalization (e.g. é as single codepoint, not e + combining accent)
    text = unicodedata.normalize("NFC", text)
    # 2. Remove zero-width / invisible characters
    text = _ZERO_WIDTH.sub("", text)
    # 3. Replace non-standard whitespace with regular space
    text = _NONSTANDARD_SPACE.sub(" ", text)
    # 4. Lowercase
    text = text.lower()
    # 5. Collapse multiple spaces and strip
    text = _MULTI_SPACE.sub(" ", text).strip()
    return text
