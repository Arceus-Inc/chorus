"""`ResendEmailBackend` — the live email transport, over Resend's REST API.

``POST https://api.resend.com/emails`` with bearer auth sends the message for real; the returned
``id`` becomes the landed ref (openable in the Resend dashboard). Injected :class:`httpx.Client`
(MockTransport-tested); non-2xx or a missing ``id`` raises :class:`DeliveryError`. Selected by
config when ``RESEND_API_KEY`` is in env — the model never chooses the transport.
"""

from __future__ import annotations

import httpx

from chorus_tools.delivery._email_types import EmailMessage
from chorus_tools.delivery._types import DeliveryError, PublishedRef

_ENDPOINT = "https://api.resend.com/emails"
_DASHBOARD = "https://resend.com/emails"


class ResendEmailBackend:
    """Send via Resend with an injected client; the message id is the delivery evidence."""

    def __init__(self, api_key: str, *, client: httpx.Client) -> None:
        self._api_key = api_key
        self._client = client

    def send(self, message: EmailMessage) -> PublishedRef:
        response = self._client.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "from": message.sender,
                "to": list(message.recipients),
                "subject": message.subject,
                "text": message.body,
            },
        )
        if response.status_code // 100 != 2:
            raise DeliveryError(f"resend send {response.status_code}: {response.text[:200]}")
        message_id = _message_id(response)
        return PublishedRef(backend="resend", ref_id=message_id, url=f"{_DASHBOARD}/{message_id}")


def _message_id(response: httpx.Response) -> str:
    payload = response.json()
    message_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(message_id, str) or not message_id:
        raise DeliveryError("resend response missing id")
    return message_id


__all__ = ["ResendEmailBackend"]
