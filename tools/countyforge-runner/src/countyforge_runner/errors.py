"""Stable, secret-safe kernel failures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class KernelError(Exception):
    """A structured failure whose message never includes untrusted values."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 2

    def as_document(self) -> dict[str, Any]:
        """Return the stable machine-readable error envelope."""

        return {
            "ok": False,
            "disposition": self.code,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }
