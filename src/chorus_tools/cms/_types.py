"""The `cms.draft` domain types — one typed value per channel (design doc: content model).

Each channel is its own frozen dataclass with the fields that channel actually has — never a bag of
magic string keys. Every draft validates its required fields on construction and exposes a uniform
:class:`CmsDraft` shape (``content_type`` + ``fields()`` + ``slug_seed()``) so a backend can render it
without knowing the concrete type. :class:`DraftRef` is the backend-agnostic result of a create.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ContentType(StrEnum):
    """The channel a draft targets — the discriminator that routes it to a collection."""

    BLOG = "blog"
    SOCIAL = "social"
    EMAIL = "email"


class SocialPlatform(StrEnum):
    """The social network a :class:`SocialDraft` is written for."""

    LINKEDIN = "linkedin"
    X = "x"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class CmsError(RuntimeError):
    """A CMS backend failed to create a draft (network, auth, or a rejected payload)."""


@runtime_checkable
class CmsDraft(Protocol):
    """The uniform shape a backend renders — implemented by each per-channel draft type."""

    @property
    def content_type(self) -> ContentType: ...

    def fields(self) -> dict[str, str]:
        """The API field map for this draft — required fields plus any set optionals, empties omitted."""
        ...

    def slug_seed(self) -> str:
        """The human text a Markdown backend slugifies into a filename."""
        ...


@dataclass(frozen=True, slots=True)
class BlogDraft:
    """Long-form blog content (`content_type=blog`)."""

    title: str
    body: str
    slug: str = ""
    excerpt: str = ""
    seo_description: str = ""

    def __post_init__(self) -> None:
        _require(self.title, "title")
        _require(self.body, "body")

    @property
    def content_type(self) -> ContentType:
        return ContentType.BLOG

    def fields(self) -> dict[str, str]:
        out = {"title": self.title, "body": self.body}
        _put(out, "slug", self.slug)
        _put(out, "excerpt", self.excerpt)
        _put(out, "seo_description", self.seo_description)
        return out

    def slug_seed(self) -> str:
        return self.title


@dataclass(frozen=True, slots=True)
class SocialDraft:
    """Short-form social content (`content_type=social`) — the text *is* the content, no title."""

    platform: SocialPlatform
    text: str
    link: str = ""
    scheduled_at: str = ""

    def __post_init__(self) -> None:
        _require(self.text, "text")

    @property
    def content_type(self) -> ContentType:
        return ContentType.SOCIAL

    def fields(self) -> dict[str, str]:
        out = {"platform": self.platform.value, "text": self.text}
        _put(out, "link", self.link)
        _put(out, "scheduled_at", self.scheduled_at)
        return out

    def slug_seed(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class EmailDraft:
    """Email / lifecycle content (`content_type=email`)."""

    subject: str
    body: str
    preheader: str = ""
    segment: str = ""

    def __post_init__(self) -> None:
        _require(self.subject, "subject")
        _require(self.body, "body")

    @property
    def content_type(self) -> ContentType:
        return ContentType.EMAIL

    def fields(self) -> dict[str, str]:
        out = {"subject": self.subject, "body": self.body}
        _put(out, "preheader", self.preheader)
        _put(out, "segment", self.segment)
        return out

    def slug_seed(self) -> str:
        return self.subject


@dataclass(frozen=True, slots=True)
class DraftRef:
    """The result of a successful draft create — where the draft lives, reversibly."""

    backend: str  # "markdown" | "strapi"
    content_type: ContentType
    ref_id: str  # markdown: relative path · strapi: documentId
    url: str  # a human-openable pointer
    status: str = "draft"

    def as_dict(self) -> dict[str, str]:
        return {
            "backend": self.backend,
            "content_type": self.content_type.value,
            "ref_id": self.ref_id,
            "url": self.url,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> DraftRef:
        """Inverse of :meth:`as_dict` — rehydrate a ref persisted in the standing-draft index."""
        return cls(
            backend=data["backend"],
            content_type=ContentType(data["content_type"]),
            ref_id=data["ref_id"],
            url=data["url"],
            status=data.get("status", "draft"),
        )


def _require(value: str, name: str) -> None:
    """Raise ``ValueError`` naming ``name`` unless ``value`` is a non-blank string."""
    if not value or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _put(target: dict[str, str], key: str, value: str) -> None:
    """Add ``key`` to ``target`` only when ``value`` is non-blank (optional fields stay absent)."""
    if value and value.strip():
        target[key] = value


__all__ = [
    "BlogDraft",
    "CmsDraft",
    "CmsError",
    "ContentType",
    "DraftRef",
    "EmailDraft",
    "SocialDraft",
    "SocialPlatform",
]
