"""`CmsDraftTool` — the `cms_draft` verb the model calls (design doc: the tool).

A *reversible* CMS write, below the go-live gate (contrast :class:`~chorus_tools._go_live.GoLiveTool`,
which stages an irreversible reach for approval). The model supplies a flat, channel-discriminated
input; :meth:`CmsDraftInput.to_draft` narrows it to a typed per-channel draft (raising on a missing
required field), which the injected :class:`~chorus_tools.cms._backend.CmsBackend` turns into a draft.
Returns the observation contract on success, the recovery contract (root_cause / safe_retry /
stop_condition) on any failure — nothing is written on a rejected input.
"""

from __future__ import annotations

from pathlib import Path

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus_tools.cms._backend import CmsBackend
from chorus_tools.cms._index import CmsDraftIndex
from chorus_tools.cms._types import (
    BlogDraft,
    CmsDraft,
    CmsError,
    ContentType,
    DraftRef,
    EmailDraft,
    SocialDraft,
    SocialPlatform,
)

# Where the standing-draft index lives in the worktree (beside the beat context dream/chorus write).
_INDEX_RELATIVE = Path(".harness") / "cms-drafts.json"


class CmsDraftInput(BaseModel):
    """Flat, channel-discriminated input — the required fields depend on ``content_type``.

    Flat (not a `oneOf` union) so weaker models call it reliably; :meth:`to_draft` enforces the
    per-type requirements by constructing the typed draft (which validates on __post_init__).
    """

    content_type: ContentType = Field(
        description="blog | social | email — the channel to draft for"
    )
    # blog / email
    title: str = Field(default="", description="blog title (blog)")
    body: str = Field(default="", description="the markdown body (blog, email)")
    slug: str = Field(default="", description="optional url slug (blog)")
    excerpt: str = Field(default="", description="optional excerpt (blog)")
    seo_description: str = Field(default="", description="optional SEO description (blog)")
    subject: str = Field(default="", description="email subject line (email)")
    preheader: str = Field(default="", description="optional email preheader (email)")
    segment: str = Field(default="", description="optional audience segment (email)")
    # social
    platform: SocialPlatform | None = Field(
        default=None, description="social network: linkedin | x | facebook | instagram (social)"
    )
    text: str = Field(default="", description="the post copy (social)")
    link: str = Field(default="", description="optional link (social)")
    scheduled_at: str = Field(default="", description="optional ISO schedule time (social)")

    def to_draft(self) -> CmsDraft:
        """Narrow to the typed draft for ``content_type`` (raises ``ValueError`` if required fields miss)."""
        if self.content_type is ContentType.BLOG:
            return BlogDraft(
                title=self.title,
                body=self.body,
                slug=self.slug,
                excerpt=self.excerpt,
                seo_description=self.seo_description,
            )
        if self.content_type is ContentType.SOCIAL:
            if self.platform is None:
                raise ValueError("a social draft requires 'platform'")
            return SocialDraft(
                platform=self.platform,
                text=self.text,
                link=self.link,
                scheduled_at=self.scheduled_at,
            )
        return EmailDraft(
            subject=self.subject,
            body=self.body,
            preheader=self.preheader,
            segment=self.segment,
        )


class CmsDraftTool(BaseTool):
    """Stage finished content as a reversible CMS draft — the Channel's pre-gate write (§08)."""

    name = "cms_draft"
    description = (
        "Stage finished content as an UNPUBLISHED draft in the CMS (reversible — nothing goes live). "
        "Pick content_type (blog|social|email) and give that channel's fields: blog needs title+body; "
        "social needs platform+text; email needs subject+body. Draft and self-review first; call this "
        "only on final content. To then publish it, use stage_go_live(publish) — a separate, gated step."
    )
    # tier_required=1 (REPO_WRITE): a reversible external write, gated like DecomposeTool/GoLiveTool.
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=20.0)
    input_model = CmsDraftInput

    def __init__(self, backend: CmsBackend) -> None:
        self._backend = backend

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            draft = CmsDraftInput.model_validate(input).to_draft()
        except (ValidationError, ValueError) as exc:
            return _rejected(str(exc))
        # Idempotency: within a task, one draft per content_type — a re-stage updates it in place.
        key = _standing_key(ctx.working_dir, draft.content_type)
        index = CmsDraftIndex(ctx.working_dir / _INDEX_RELATIVE) if key is not None else None
        standing = index.standing_ref(key) if index is not None and key is not None else None
        try:
            if standing is not None:
                ref, action = self._backend.update_draft(standing.ref_id, draft), "updated"
            else:
                ref, action = self._backend.create_draft(draft), "staged"
        except CmsError as exc:
            return _failed(str(exc))
        if index is not None and key is not None:
            index.record(key, ref)
        return _drafted(ref, action)


def _standing_key(working_dir: Path, content_type: ContentType) -> str | None:
    """The idempotency key for this beat's content_type, or ``None`` when there's no beat context.

    Reading the beat context (``.harness/beat-context.json``) is best-effort: outside a real beat
    (a local run or a unit test) there is no task identity, so idempotency simply doesn't engage.
    """
    from chorus_tools._beat import task_id_or_none

    task_id = task_id_or_none(working_dir)
    if task_id is None:
        return None
    return f"{content_type.value}:{task_id}"


def _drafted(ref: DraftRef, action: str) -> ToolResult:
    publish_action = f"stage_go_live(publish, target={ref.ref_id})"
    return ToolResult(
        content=(
            "status: success\n"
            f"summary: {action} a {ref.content_type.value} draft in the CMS ({ref.backend}) — id {ref.ref_id}\n"
            f"next_actions: review the draft, then {publish_action} to publish it\n"
            f"artifacts: {ref.as_dict()}"
        ),
        is_error=False,
        metadata={
            "status": "success",
            "draft_ref": ref.as_dict(),
            "next_actions": ["review the draft", publish_action],
        },
    )


def _rejected(detail: str) -> ToolResult:
    return ToolResult(
        content=(
            "status: error\n"
            f"summary: no draft staged — {detail}\n"
            "root_cause: the request failed the cms_draft schema\n"
            "safe_retry: re-issue with content_type set and that channel's required fields "
            "(blog: title+body · social: platform+text · email: subject+body)\n"
            "stop_condition: do not retry the same payload; nothing was staged"
        ),
        is_error=True,
    )


def _failed(detail: str) -> ToolResult:
    return ToolResult(
        content=(
            "status: error\n"
            f"summary: the CMS rejected the draft — {detail}\n"
            "root_cause: the backend returned an error (auth, network, or a rejected payload)\n"
            "safe_retry: verify the CMS is reachable and the token is valid, then retry once\n"
            "stop_condition: if it fails again, stop — the CMS is unavailable, not the content"
        ),
        is_error=True,
    )


__all__ = ["CmsDraftInput", "CmsDraftTool"]
