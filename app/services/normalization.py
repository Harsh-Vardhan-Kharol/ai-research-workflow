"""Small, explainable normalization for exact-value comparison keys."""

from __future__ import annotations

import unicodedata


def normalize_comparison_value(value: str) -> str:
    """Casefold and normalize whitespace/punctuation without semantic matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    chars = [" " if unicodedata.category(char).startswith("P") else char for char in normalized]
    return " ".join("".join(chars).split())
