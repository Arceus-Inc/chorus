"""Delivery-backend selection — config decides the target, never the model (design doc: wiring).

Mirrors the cms backend selection: hosted backends only when their env is fully set (Strapi for
publish, Resend for email), else the keyless defaults rooted in the worktree (Markdown flip,
file outbox). Partial env never half-wires a hosted backend; secrets come from env only.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from chorus_tools._http import HTTP_TIMEOUT_S
from chorus_tools.cms import cms_backend_from_env
from chorus_tools.delivery._backend import PublishBackend
from chorus_tools.delivery._email_backend import EmailBackend
from chorus_tools.delivery._email_types import email_routing_from_env
from chorus_tools.delivery._markdown_publish import MarkdownPublishBackend
from chorus_tools.delivery._outbox_email import OutboxEmailBackend
from chorus_tools.delivery._resend_email import ResendEmailBackend
from chorus_tools.delivery._send import EmailDelivery
from chorus_tools.delivery._strapi_publish import StrapiPublishBackend


def publish_backend_from_env(markdown_root: Path) -> PublishBackend:
    """Return the Strapi publish backend when its env is fully set, else the Markdown flip."""
    base_url = os.environ.get("STRAPI_URL")
    token = os.environ.get("STRAPI_TOKEN")
    if base_url and token:
        return StrapiPublishBackend(base_url, token, client=httpx.Client(timeout=HTTP_TIMEOUT_S))
    return MarkdownPublishBackend(markdown_root)


def email_backend_from_env(markdown_root: Path) -> EmailBackend:
    """Return the live Resend transport when ``RESEND_API_KEY`` is set, else the file outbox."""
    api_key = os.environ.get("RESEND_API_KEY")
    if api_key:
        return ResendEmailBackend(api_key, client=httpx.Client(timeout=HTTP_TIMEOUT_S))
    return OutboxEmailBackend(markdown_root)


def email_delivery_from_env(markdown_root: Path) -> EmailDelivery:
    """The full send path from env: cms content source + transport + operator routing."""
    return EmailDelivery(
        cms_backend_from_env(markdown_root),
        email_backend_from_env(markdown_root),
        email_routing_from_env(),
    )


__all__ = ["email_backend_from_env", "email_delivery_from_env", "publish_backend_from_env"]
