"""Email channel — send an approved draft over an ESP (or a file outbox).

The :class:`EmailBackend` transport seam and its two implementations —
:class:`ResendEmailBackend` (live ESP) and :class:`OutboxEmailBackend` (keyless file outbox) —
plus the value objects (:class:`EmailMessage`, :class:`EmailRouting`), the markdown→HTML render,
and :class:`EmailDelivery`, which marries an approved CMS draft to the transport. Routing comes from
operator env (:func:`email_routing_from_env`); the model never chooses recipients.
"""

from __future__ import annotations

from chorus_tools.delivery.email._backend import EmailBackend
from chorus_tools.delivery.email._html import render_email_html
from chorus_tools.delivery.email._outbox import OutboxEmailBackend
from chorus_tools.delivery.email._resend import ResendEmailBackend
from chorus_tools.delivery.email._send import EmailDelivery
from chorus_tools.delivery.email._types import (
    EmailMessage,
    EmailRouting,
    email_routing_from_env,
)

__all__ = [
    "EmailBackend",
    "EmailDelivery",
    "EmailMessage",
    "EmailRouting",
    "OutboxEmailBackend",
    "ResendEmailBackend",
    "email_routing_from_env",
    "render_email_html",
]
