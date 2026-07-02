"""`OutboxEmailBackend` — the keyless email transport: an approved send lands as a file.

The Markdown-backend analogy for email: instead of hitting an ESP, the executed send writes a
complete ``.eml``-style file under ``outbox/`` in the worktree — headers + body, openable in any
editor. Deterministic, inspectable, zero credentials; the same seam Resend plugs into.
"""

from __future__ import annotations

import re
from pathlib import Path

from chorus_tools._backends import BackendName
from chorus_tools.delivery._email_types import EmailMessage
from chorus_tools.delivery._types import PublishedRef

_OUTBOX_DIR = "outbox"
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 48


class OutboxEmailBackend:
    """Write each sent message as a numbered .eml file under the outbox root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def send(self, message: EmailMessage, *, idempotency_key: str) -> PublishedRef:
        outbox = self._root / _OUTBOX_DIR
        outbox.mkdir(parents=True, exist_ok=True)
        # Filename is derived from the key so a retry of the same send overwrites its file rather than
        # dropping a second one — at-most-once, matching the live ESP's Idempotency-Key behaviour.
        relative = Path(_OUTBOX_DIR) / f"{_slug(idempotency_key)}-{_slug(message.subject)}.eml"
        path = self._root / relative
        path.write_text(_render(message), encoding="utf-8")
        return PublishedRef(
            backend=BackendName.OUTBOX.value, ref_id=str(relative), url=path.as_uri()
        )


def _render(message: EmailMessage) -> str:
    headers = [
        f"From: {message.sender}",
        f"To: {', '.join(message.recipients)}",
        f"Subject: {message.subject}",
    ]
    if message.preheader:
        headers.append(f"X-Preheader: {message.preheader}")
    return "\n".join(headers) + "\n\n" + message.body + "\n"


def _slug(subject: str) -> str:
    slug = _NON_SLUG.sub("-", subject.lower()).strip("-")[:_SLUG_MAX].strip("-")
    return slug or "email"


__all__ = ["OutboxEmailBackend"]
