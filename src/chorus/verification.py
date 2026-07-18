"""Built-in verification identities that are not members of the workforce."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationPrincipal:
    """A durable system actor that independently verifies employee-authored work."""

    id: str
    name: str
    kind: str = "verification"


SYSTEM_VERIFIER = VerificationPrincipal(id="system-verifier", name="System Verifier")


__all__ = ["SYSTEM_VERIFIER", "VerificationPrincipal"]
