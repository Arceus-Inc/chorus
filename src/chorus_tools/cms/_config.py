"""Backend selection for `cms_draft` — config decides the target, never the model (design doc: wiring).

When `STRAPI_URL` + `STRAPI_TOKEN` are both in the environment, drafts go to the hosted Strapi backend;
otherwise they fall back to the keyless Markdown backend rooted in the worktree. Partial config never
half-wires a hosted backend — both vars must be present. Secrets are read from env only, never inline.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from chorus_tools.cms._backend import CmsBackend
from chorus_tools.cms._markdown import MarkdownCmsBackend
from chorus_tools.cms._strapi import StrapiCmsBackend

_HTTP_TIMEOUT_S = 20.0


def cms_backend_from_env(markdown_root: Path) -> CmsBackend:
    """Return the Strapi backend when its env is fully set, else the Markdown backend."""
    base_url = os.environ.get("STRAPI_URL")
    token = os.environ.get("STRAPI_TOKEN")
    if base_url and token:
        return StrapiCmsBackend(base_url, token, client=httpx.Client(timeout=_HTTP_TIMEOUT_S))
    return MarkdownCmsBackend(markdown_root)


__all__ = ["cms_backend_from_env"]
