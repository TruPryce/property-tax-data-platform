"""Stable sanitized control-plane errors."""

from __future__ import annotations

from typing import Any


class ControlPlaneError(Exception):
    """A safe machine-readable control-plane failure."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        exit_code: int = 2,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code

    def as_document(self) -> dict[str, Any]:
        """Return the bounded public error representation."""

        return {
            "ok": False,
            "disposition": self.code,
            "message": self.message,
            "details": self.details,
        }
