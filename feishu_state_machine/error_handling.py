"""Internal error taxonomy. Categories must never be rendered to users."""

from __future__ import annotations


class OperationError(Exception):
    def __init__(self, category: str, *, retryable: bool, message: str = "operation failed"):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


def classify_exception(exc: BaseException) -> tuple[str, bool]:
    category = getattr(exc, "category", None)
    retryable = getattr(exc, "retryable", None)
    if category is not None and retryable is not None:
        return str(category), bool(retryable)

    name = exc.__class__.__name__.lower()
    if "timeout" in name or "connection" in name:
        return "transient_network", True
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "data_validation", False
    if isinstance(exc, OSError):
        return "transient_network", True
    return "engine_unavailable", True
