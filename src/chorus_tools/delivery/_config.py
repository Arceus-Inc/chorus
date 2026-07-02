"""Publish-backend selection — config decides the target, never the model (design doc: wiring).

Mirrors the cms backend selection: Strapi when ``STRAPI_URL`` + ``STRAPI_TOKEN`` are both in env,
else the keyless Markdown flip rooted in the worktree. Partial env never half-wires a hosted
backend; secrets come from env only.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from chorus_tools.delivery._backend import PublishBackend
from chorus_tools.delivery._markdown_publish import MarkdownPublishBackend
from chorus_tools.delivery._strapi_publish import StrapiPublishBackend

_HTTP_TIMEOUT_S = 20.0


def publish_backend_from_env(markdown_root: Path) -> PublishBackend:
    """Return the Strapi publish backend when its env is fully set, else the Markdown flip."""
    base_url = os.environ.get("STRAPI_URL")
    token = os.environ.get("STRAPI_TOKEN")
    if base_url and token:
        return StrapiPublishBackend(base_url, token, client=httpx.Client(timeout=_HTTP_TIMEOUT_S))
    return MarkdownPublishBackend(markdown_root)


__all__ = ["publish_backend_from_env"]
