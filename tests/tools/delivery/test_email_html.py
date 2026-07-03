"""Email markdown→HTML — content drafted in markdown must render wherever md can't go (gmail).

A small deterministic renderer for the email subset (headings, paragraphs, bold/italic/code,
lists, links, hr) with escaping — and the Resend transport sends BOTH html (rendered) and text
(plain fallback).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from chorus_tools.delivery._email_html import render_email_html
from chorus_tools.delivery._email_types import EmailMessage
from chorus_tools.delivery._resend_email import ResendEmailBackend

pytestmark = pytest.mark.unit


class TestRenderEmailHtml:
    def test_heading_and_paragraph(self) -> None:
        html = render_email_html("# Big news\n\nHello there.")
        assert "<h1" in html and "Big news" in html
        assert "<p" in html and "Hello there." in html
        assert "# Big news" not in html  # no raw markdown survives

    def test_bold_italic_code(self) -> None:
        html = render_email_html("This is **bold**, *soft*, and `code`.")
        assert "<strong>bold</strong>" in html
        assert "<em>soft</em>" in html
        assert "<code" in html and "code" in html

    def test_unordered_and_ordered_lists(self) -> None:
        html = render_email_html("- one\n- two\n\n1. first\n2. second")
        assert html.count("<li>") == 4
        assert "<ul" in html and "<ol" in html

    def test_links_are_anchors(self) -> None:
        html = render_email_html("See [Arceus](https://arceus.sh) today.")
        assert '<a href="https://arceus.sh"' in html and ">Arceus</a>" in html

    def test_horizontal_rule(self) -> None:
        assert "<hr" in render_email_html("above\n\n---\n\nbelow")

    def test_html_is_escaped(self) -> None:
        html = render_email_html("evil <script>alert(1)</script> & co")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp; co" in html


class TestResendSendsHtmlAndText:
    def test_payload_carries_both_bodies(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            handler.request = request  # type: ignore[attr-defined]
            return httpx.Response(200, json={"id": "msg_9"})

        backend = ResendEmailBackend(
            "re_k", client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        message = EmailMessage(
            sender="mira@arceus.sh",
            recipients=("r@x.io",),
            subject="Launch",
            body="# Hi\n\n**Bold** move.",
        )

        backend.send(message, idempotency_key="apr_1")

        req: Any = handler.request  # type: ignore[attr-defined]
        payload = json.loads(req.content)
        assert payload["text"] == "# Hi\n\n**Bold** move."  # plain fallback stays raw
        assert "<strong>Bold</strong>" in payload["html"]
        assert "# Hi" not in payload["html"]
