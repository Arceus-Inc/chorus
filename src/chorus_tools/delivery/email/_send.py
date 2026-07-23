"""`EmailDelivery` — where approved content meets the email transport (email-send design).

The send half of the executor: read the STAGED email draft back from the CMS (the model can never
smuggle different copy past the gate), compose it onto the operator-configured routing, and hand it
to the transport. Any CMS read failure or a non-email draft is a :class:`DeliveryError` — nothing
half-sends.
"""

from __future__ import annotations

from chorus_tools.cms import CmsBackend, CmsError, ContentType, DraftRef, EmailDraft
from chorus_tools.delivery._types import DeliveryError, PublishedRef
from chorus_tools.delivery.email._backend import EmailBackend
from chorus_tools.delivery.email._types import EmailMessage, EmailRouting


class EmailDelivery:
    """Send the staged email draft over the configured transport — approved content only."""

    def __init__(self, cms: CmsBackend, transport: EmailBackend, routing: EmailRouting) -> None:
        self._cms = cms
        self._transport = transport
        self._routing = routing

    def send(self, draft: DraftRef, *, idempotency_key: str) -> PublishedRef:
        if draft.content_type is not ContentType.EMAIL:
            raise DeliveryError(
                f"only an email draft can be sent — got content_type={draft.content_type.value!r}"
            )
        try:
            staged = self._cms.read_draft(draft.ref_id, ContentType.EMAIL)
        except CmsError as exc:
            raise DeliveryError(f"could not read the staged email draft: {exc}") from exc
        if not isinstance(staged, EmailDraft):  # narrowing for the type system; read is by type
            raise DeliveryError("staged draft is not an email draft")
        message = EmailMessage.compose(self._routing, staged)
        return self._transport.send(message, idempotency_key=idempotency_key)


__all__ = ["EmailDelivery"]
