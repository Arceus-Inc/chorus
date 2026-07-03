"""Email value objects — routing is config, content is the approved draft (email-send design).

:class:`EmailRouting` carries WHO an approved send reaches — sender + recipients from env, never
from the model (§11: the blast radius stays with the operator). :class:`EmailMessage` marries that
routing to the staged draft's content. Both frozen, both validating.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from chorus_tools.cms import EmailDraft

_DEFAULT_SENDER = "mira@localhost"
_DEFAULT_RECIPIENT = "outbox@localhost"


@dataclass(frozen=True, slots=True)
class EmailRouting:
    """Sender + audience for outbound email — operator config, never model input."""

    sender: str
    recipients: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.sender or not self.sender.strip():
            raise ValueError("sender must be a non-empty string")
        if not self.recipients or any(not r.strip() for r in self.recipients):
            raise ValueError("recipients must be a non-empty tuple of addresses")


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """One outbound email: config routing + the APPROVED draft's content."""

    sender: str
    recipients: tuple[str, ...]
    subject: str
    body: str
    preheader: str = ""

    def __post_init__(self) -> None:
        if not self.subject or not self.subject.strip():
            raise ValueError("subject must be a non-empty string")
        if not self.body or not self.body.strip():
            raise ValueError("body must be a non-empty string")

    @classmethod
    def compose(cls, routing: EmailRouting, draft: EmailDraft) -> EmailMessage:
        """The staged draft's content on the configured route — what actually sends."""
        return cls(
            sender=routing.sender,
            recipients=routing.recipients,
            subject=draft.subject,
            body=draft.body,
            preheader=draft.preheader,
        )


def email_routing_from_env() -> EmailRouting:
    """Routing from ``EMAIL_FROM`` / ``EMAIL_TO`` (comma list); keyless localhost defaults."""
    sender = os.environ.get("EMAIL_FROM", "").strip() or _DEFAULT_SENDER
    raw = os.environ.get("EMAIL_TO", "")
    recipients = tuple(part.strip() for part in raw.split(",") if part.strip())
    return EmailRouting(sender=sender, recipients=recipients or (_DEFAULT_RECIPIENT,))


__all__ = ["EmailMessage", "EmailRouting", "email_routing_from_env"]
