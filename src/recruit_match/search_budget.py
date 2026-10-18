"""Shared Search Agent call-budget policy."""
from __future__ import annotations

DEFAULT_CALLS = 20
MAX_CALLS = 100


def validate_call_budget(value: int, *, error_code: str) -> int:
    """Return a valid budget in the inclusive range 1..MAX_CALLS."""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > MAX_CALLS
    ):
        raise ValueError(error_code)
    return value
