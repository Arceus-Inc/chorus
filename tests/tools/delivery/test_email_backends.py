"""Email transports — Outbox (keyless .eml files) and Resend (live API) + routing/message types.

Routing is CONFIG, never the model (§11 blast radius): sender/recipients come from env via
EmailRouting. The message carries the APPROVED draft content. Outbox writes an inspectable file;
Resend POSTs with bearer auth (MockTransport here; the live e2e uses a real key).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import httpx
import pytest

from chorus_tools.delivery import DeliveryError
from chorus_tools.delivery._email_types import (
    EmailMessage,
    EmailRouting,
    email_routing_from_env,
)
from chorus_tools.delivery._outbox_email import OutboxEmailBackend
from chorus_tools.delivery._resend_email import ResendEmailBackend

pytestmark = pytest.mark.unit


def _message(subject: str = "Launch news") -> EmailMessage:
    return EmailMessage(
        sender="mira@arceus.sh",
        recipients=("a@x.io", "b@x.io"),
        subject=subject,
        body="Hello!\n\nBig news.",
        preheader="pre",
    )


class TestEmailRouting:
    def test_frozen_and_validated(self) -> None:
        routing = EmailRouting(sender="s@x.io", recipients=("r@x.io",))
        with pytest.raises(dataclasses.FrozenInstanceError):
            routing.sender = "y"  # type: ignore[misc]
        with pytest.raises(ValueError, match="sender"):
            EmailRouting(sender=" ", recipients=("r@x.io",))
        with pytest.raises(ValueError, match="recipients"):
            EmailRouting(sender="s@x.io", recipients=())

    def test_from_env_parses_comma_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EMAIL_FROM", "mira@arceus.sh")
        monkeypatch.setenv("EMAIL_TO", "a@x.io, b@x.io")
        routing = email_routing_from_env()
        assert routing == EmailRouting(sender="mira@arceus.sh", recipients=("a@x.io", "b@x.io"))

    def test_from_env_defaults_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EMAIL_FROM", raising=False)
        monkeypatch.delenv("EMAIL_TO", raising=False)
        routing = email_routing_from_env()
        assert routing.sender and routing.recipients  # keyless defaults exist


class TestEmailMessage:
    def test_validates_required(self) -> None:
        with pytest.raises(ValueError, match="subject"):
            EmailMessage(sender="s@x.io", recipients=("r@x.io",), subject=" ", body="B")


class TestOutboxEmail:
    def test_writes_an_eml_file_with_headers_and_body(self, tmp_path: Path) -> None:
        landed = OutboxEmailBackend(tmp_path).send(_message())

        assert landed.backend == "outbox"
        path = tmp_path / landed.ref_id
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "From: mira@arceus.sh" in text
        assert "To: a@x.io, b@x.io" in text
        assert "Subject: Launch news" in text
        assert "X-Preheader: pre" in text
        assert "Big news." in text

    def test_sequential_sends_get_distinct_files(self, tmp_path: Path) -> None:
        backend = OutboxEmailBackend(tmp_path)
        first = backend.send(_message("One"))
        second = backend.send(_message("Two"))
        assert first.ref_id != second.ref_id
        assert (tmp_path / first.ref_id).is_file() and (tmp_path / second.ref_id).is_file()


def _resend(handler: Any) -> ResendEmailBackend:
    return ResendEmailBackend(
        "re_test_key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


class TestResendEmail:
    def test_posts_the_message_with_bearer_auth(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            handler.request = request  # type: ignore[attr-defined]
            return httpx.Response(200, json={"id": "msg_123"})

        landed = _resend(handler).send(_message())

        import json

        req: httpx.Request = handler.request  # type: ignore[attr-defined]
        assert req.method == "POST"
        assert str(req.url) == "https://api.resend.com/emails"
        assert req.headers["authorization"] == "Bearer re_test_key"
        payload = json.loads(req.content)
        assert payload["from"] == "mira@arceus.sh"
        assert payload["to"] == ["a@x.io", "b@x.io"]
        assert payload["subject"] == "Launch news"
        assert payload["text"] == "Hello!\n\nBig news."
        assert "Big news." in payload["html"]  # rendered part rides along
        assert landed.backend == "resend"
        assert landed.ref_id == "msg_123"
        assert "msg_123" in landed.url

    def test_non_2xx_raises_delivery_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "invalid from"})

        with pytest.raises(DeliveryError, match="422"):
            _resend(handler).send(_message())

    def test_missing_id_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        with pytest.raises(DeliveryError, match="id"):
            _resend(handler).send(_message())


class TestEmailBackendFromEnv:
    def test_outbox_when_resend_key_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        from chorus_tools.delivery import email_backend_from_env

        assert isinstance(email_backend_from_env(tmp_path), OutboxEmailBackend)

    def test_resend_when_key_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RESEND_API_KEY", "re_x")
        from chorus_tools.delivery import email_backend_from_env

        assert isinstance(email_backend_from_env(tmp_path), ResendEmailBackend)
