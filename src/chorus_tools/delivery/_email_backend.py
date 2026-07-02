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
    """Send a composed message; raise :class:`DeliveryError` on failure.

    ``idempotency_key`` is a stable per-approval token (the go-live gate id). A send is at-most-once
    with no delivery record written until it succeeds, so a retry after a provider-accepted-then-errored
    call could double-send; passing the same key lets the transport dedupe that retry.
    """

    def send(self, message: EmailMessage, *, idempotency_key: str) -> PublishedRef: ...


__all__ = ["EmailBackend"]
