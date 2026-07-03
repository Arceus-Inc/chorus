"""Delivery value objects — what an executed go-live leaves behind (design doc: components).

:class:`PublishedRef` is what a publish backend reports (where the content now lives, live).
:class:`DeliveryRecord` is the standing delivery per approval — the auditable "this gate was
executed exactly once, here" row, persisted in the worktree delivery index. Frozen, slotted,
with validating dict round-trips so the index can never silently hold a malformed record.
"""

from __future__ import annotations

from dataclasses import dataclass

from chorus_tools._go_live import GoLiveAction
from chorus_tools._validate import require as _require


class DeliveryError(RuntimeError):
    """A delivery backend failed to execute the approved reach (network, auth, missing target)."""


@dataclass(frozen=True, slots=True)
class PublishedRef:
    """Where the published content now lives — reported by the backend after a successful publish."""

    backend: str  # "strapi" | "markdown"
    ref_id: str  # strapi: documentId · markdown: relative path
    url: str  # a human-openable pointer to the LIVE content

    def __post_init__(self) -> None:
        _require(self.backend, "backend")
        _require(self.ref_id, "ref_id")
        _require(self.url, "url")


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """One executed go-live: which approval authorised it, what reach, and where it landed."""

    approval_id: str
    action: GoLiveAction
    target: str
    published: PublishedRef

    def __post_init__(self) -> None:
        _require(self.approval_id, "approval_id")
        _require(self.target, "target")

    def as_dict(self) -> dict[str, str]:
        """Flat, JSON-safe shape for the delivery index."""
        return {
            "approval_id": self.approval_id,
            "action": self.action.value,
            "target": self.target,
            "backend": self.published.backend,
            "ref_id": self.published.ref_id,
            "url": self.published.url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> DeliveryRecord:
        """Inverse of :meth:`as_dict`; raises ``ValueError`` on a missing/malformed field."""
        for key in ("approval_id", "action", "target", "backend", "ref_id", "url"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f"delivery record field {key!r} must be a non-empty string")
        return cls(
            approval_id=data["approval_id"],
            action=GoLiveAction(data["action"]),
            target=data["target"],
            published=PublishedRef(backend=data["backend"], ref_id=data["ref_id"], url=data["url"]),
        )


__all__ = ["DeliveryError", "DeliveryRecord", "PublishedRef"]
