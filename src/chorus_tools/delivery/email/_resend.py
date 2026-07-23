"""`ResendEmailBackend` — the live email transport, over Resend's REST API.

``POST https://api.resend.com/emails`` with bearer auth sends the message for real; the returned
``id`` becomes the landed ref (openable in the Resend dashboard). Injected :class:`httpx.Client`
(MockTransport-tested); non-2xx or a missing ``id`` raises :class:`DeliveryError`. Selected by
config when ``RESEND_API_KEY`` is in env — the model never chooses the transport.
"""

from __future__ import annotations

import httpx

from chorus_tools._backends import BackendName
from chorus_tools._http import ensure_ok, json_body
from chorus_tools.delivery._types import DeliveryError, PublishedRef
from chorus_tools.delivery.email._html import render_email_html
from chorus_tools.delivery.email._types import EmailMessage

_ENDPOINT = "https://api.resend.com/emails"
_DASHBOARD = "https://resend.com/emails"


class ResendEmailBackend:
    """Send via Resend with an injected client; the message id is the delivery evidence."""

    def __init__(self, api_key: str, *, client: httpx.Client) -> None:
        self._api_key = api_key
        self._client = client

    def send(self, message: EmailMessage, *, idempotency_key: str) -> PublishedRef:
        response = self._client.post(
            _ENDPOINT,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                # Resend dedupes retries carrying the same key — the at-most-once guard for a send
                # whose delivery record is only written after it succeeds.
                "Idempotency-Key": idempotency_key,
            },
            json={
                "from": message.sender,
                "to": list(message.recipients),
                "subject": message.subject,
                # Both bodies: html renders the markdown for inbox clients; text is the
                # plain-part fallback (and better deliverability than html-only).
                "text": message.body,
                "html": render_email_html(message.body),
            },
        )
        ensure_ok(response, prefix="resend send", error=DeliveryError)
        message_id = _message_id(response)
        return PublishedRef(
            backend=BackendName.RESEND.value, ref_id=message_id, url=f"{_DASHBOARD}/{message_id}"
        )


def _message_id(response: httpx.Response) -> str:
    payload = json_body(response, prefix="resend send", error=DeliveryError)
    message_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(message_id, str) or not message_id:
        raise DeliveryError("resend send: response missing id")
    return message_id


__all__ = ["ResendEmailBackend"]
