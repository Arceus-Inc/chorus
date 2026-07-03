"""`cms.draft` — the marketer's reversible CMS write, per-channel and backend-swappable.

Public surface: the per-channel draft types + :class:`DraftRef` (this module), the
:class:`CmsBackend` seam with its Markdown + Strapi implementations, and the :class:`CmsDraftTool`
that exposes the ``cms_draft`` verb to the model.
"""

from __future__ import annotations

from chorus_tools.cms._backend import CmsBackend
from chorus_tools.cms._config import cms_backend_from_env
from chorus_tools.cms._markdown import MarkdownCmsBackend
from chorus_tools.cms._strapi import StrapiCmsBackend
from chorus_tools.cms._tool import CmsDraftInput, CmsDraftTool
from chorus_tools.cms._types import (
    BlogDraft,
    CmsDraft,
    CmsError,
    ContentType,
    DraftRef,
    EmailDraft,
    SocialDraft,
    SocialPlatform,
    draft_from_fields,
)

__all__ = [
    "BlogDraft",
    "CmsBackend",
    "CmsDraft",
    "CmsDraftInput",
    "CmsDraftTool",
    "CmsError",
    "ContentType",
    "DraftRef",
    "EmailDraft",
    "MarkdownCmsBackend",
    "SocialDraft",
    "SocialPlatform",
    "StrapiCmsBackend",
    "cms_backend_from_env",
    "draft_from_fields",
]
