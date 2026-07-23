"""The backend-name vocabulary — one source of truth for the transport labels.

The ``backend`` field on ``DraftRef`` / ``PublishedRef`` / ``DeliveryRecord`` used to be a bare
string literal (``"strapi"``, ``"resend"``, ``"markdown"``, ``"outbox"``) written at each backend's
construction site — a silent-drift risk. ``BackendName`` is a ``StrEnum`` so members compare and
serialize as their string value (``BackendName.STRAPI == "strapi"``); construction sites pass
``BackendName.X.value`` and the persisted/asserted strings are unchanged.
"""

from __future__ import annotations

from enum import StrEnum


class BackendName(StrEnum):
    """Stable label for a tool transport, recorded on the ref/record it produces."""

    STRAPI = "strapi"
    RESEND = "resend"
    MARKDOWN = "markdown"
    OUTBOX = "outbox"


__all__ = ["BackendName"]
