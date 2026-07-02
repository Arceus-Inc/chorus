"""The `EmailBackend` seam — the one operation an email transport implements.

Sends a composed :class:`~chorus_tools.delivery._email_types.EmailMessage` and reports where it
landed. Implementations: :class:`~chorus_tools.delivery._outbox_email.OutboxEmailBackend` (keyless
file outbox) and :class:`~chorus_tools.delivery._resend_email.ResendEmailBackend` (live ESP).
"""

from __future__ import annotations

from typing import Protocol

from chorus_tools.delivery._email_types import EmailMessage
from chorus_tools.delivery._types import PublishedRef


class EmailBackend(Protocol):
    """Send a composed message; raise :class:`DeliveryError` on failure."""

    def send(self, message: EmailMessage) -> PublishedRef: ...


__all__ = ["EmailBackend"]
