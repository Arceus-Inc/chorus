"""``design_exemplar`` — read a vendored real-world ``DESIGN.md`` exemplar (designer §08 tool).

The ``design-md-exemplars`` skill ships a vendored library of 58 real-world ``DESIGN.md`` files
(Stripe, Linear, Vercel, Notion, …) under ``chorus_employee/designer/references/awesome-design-md/``.
That tree lives in the *chorus package*, **not** in the Designer's git worktree — so a worktree-confined
``read_file`` can never reach it, and the exemplars the skill points at were effectively unreadable.

This tool closes that gap: it is a read-only verb that returns ONE named exemplar's full ``DESIGN.md``
from the vendored library, independent of the worktree (the same seam ``design_lint`` uses — a pure
file reader, no model, no network). Called with no (or an unknown) ``company`` it returns the catalog
of available exemplars so the model can pick a valid one. The Designer learns *structure and rigor*
from an exemplar and adapts it to the product's own brand — it never transplants values verbatim.

Harness contract (agent-harness-construction): a narrow typed input, a deterministic output shape
(``status`` / ``summary`` / ``artifacts``), and an explicit recovery contract
(``root_cause`` / ``safe_retry`` / ``stop_condition``) on every error path.
"""

from __future__ import annotations

import difflib
from functools import lru_cache
from pathlib import Path

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

# Guard against a pathological or malicious exemplar; the largest real one is ~26 KB.
_MAX_EXEMPLAR_BYTES = 128 * 1024


@lru_cache(maxsize=1)
def exemplars_root() -> Path:
    """The vendored exemplar library dir, resolved from the designer package (cached).

    Resolved lazily (not at import time) so ``chorus_tools`` never import-couples to
    ``chorus_employee`` — the tool is only ever constructed inside the harness factory, well after
    both packages have imported.
    """
    import chorus_employee.designer as _designer_pkg

    return Path(_designer_pkg.__file__).parent / "references" / "awesome-design-md"


def available_exemplars(root: Path | None = None) -> tuple[str, ...]:
    """The sorted company slugs that have a ``<company>/DESIGN.md`` in the library."""
    base = root if root is not None else exemplars_root()
    if not base.is_dir():
        return ()
    return tuple(sorted(p.name for p in base.iterdir() if (p / "DESIGN.md").is_file()))


class DesignExemplarInput(BaseModel):
    """Typed contract for ``design_exemplar`` — validated before any file is read."""

    company: str = Field(
        default="",
        description=(
            "the exemplar to fetch, by slug (e.g. 'stripe', 'linear.app', 'vercel'). "
            "Leave empty to list the available exemplars."
        ),
    )


def _catalog(root: Path, *, prefix: str) -> ToolResult:
    """Return the list of available exemplar slugs (the no-/bad-arg branch)."""
    names = available_exemplars(root)
    if not names:
        return ToolResult(
            content="design_exemplar: the vendored exemplar library is not available.",
            is_error=True,
            metadata={
                "root_cause": f"no exemplar library found at {root}",
                "safe_retry": "author the DESIGN.md from the design-md-exemplars skill's inline catalog + browser_run",
                "stop_condition": "the vendored library is missing from this build",
            },
        )
    listing = ", ".join(names)
    return ToolResult(
        content=f"{prefix}Available exemplars ({len(names)}): {listing}",
        is_error=False,
        metadata={
            "status": "success",
            "summary": f"{len(names)} exemplars available",
            "next_actions": [
                "Call design_exemplar(company='<slug>') with one of the listed slugs to read its DESIGN.md.",
            ],
            "artifacts": {"exemplars": list(names)},
        },
    )


class DesignExemplarTool(BaseTool):
    """Fetch one vendored real-world ``DESIGN.md`` exemplar by slug — read-only, no model, no net."""

    name = "design_exemplar"
    description = (
        "Fetch one real-world DESIGN.md exemplar (Stripe, Linear, Vercel, Notion, …) from the "
        "vendored design-system library, to learn its STRUCTURE and rigor when authoring a project's "
        "own DESIGN.md. Call with no argument to list the available exemplars, then "
        "design_exemplar(company='<slug>') to read one. Learn the shape and adapt it to THIS "
        "product's brand — never transplant an exemplar's palette/type verbatim. Args: company (slug)."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=15.0)
    input_model = DesignExemplarInput

    def __init__(self, references_root: Path | None = None) -> None:
        # Injectable for tests; defaults to the vendored library resolved from the designer package.
        self._root = references_root

    def _references(self) -> Path:
        return self._root if self._root is not None else exemplars_root()

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        del ctx  # worktree-independent: exemplars live in the chorus package, not the worktree
        try:
            args = DesignExemplarInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(
                content=f"design_exemplar rejected: {exc}",
                is_error=True,
                metadata={
                    "root_cause": str(exc),
                    "safe_retry": "call with a 'company' slug, or no argument to list exemplars",
                    "stop_condition": "the tool input was invalid",
                },
            )

        root = self._references()
        slug = args.company.strip().lower()
        if not slug:
            return _catalog(root, prefix="")

        names = available_exemplars(root)
        if slug not in names:
            hint = difflib.get_close_matches(slug, names, n=3)
            suggestion = f" Did you mean: {', '.join(hint)}?" if hint else ""
            return ToolResult(
                content=(
                    f"design_exemplar: no exemplar {args.company!r}.{suggestion}\n"
                    f"Available ({len(names)}): {', '.join(names)}"
                ),
                is_error=True,
                metadata={
                    "root_cause": f"unknown exemplar {args.company!r}",
                    "safe_retry": "call design_exemplar with a listed slug (or no argument to list)",
                    "stop_condition": "the requested exemplar is not in the vendored library",
                    "artifacts": {"exemplars": list(names)},
                },
            )

        doc = root / slug / "DESIGN.md"
        size = doc.stat().st_size
        if size > _MAX_EXEMPLAR_BYTES:
            body = doc.read_text(encoding="utf-8")[:_MAX_EXEMPLAR_BYTES]
            truncated = True
        else:
            body = doc.read_text(encoding="utf-8")
            truncated = False
        note = "\n\n[truncated — exemplar exceeded the size cap]" if truncated else ""
        header = (
            f"design_exemplar: {slug} — study the STRUCTURE (sections, rigor, level of detail); "
            f"adapt to THIS product's brand, never transplant values verbatim.\n\n"
        )
        return ToolResult(
            content=f"{header}{body}{note}",
            is_error=False,
            metadata={
                "status": "success",
                "summary": f"exemplar {slug} ({size} bytes)",
                "next_actions": [
                    "Map the product's feel to this exemplar's atmosphere, then re-derive every value from the product's own brand.",
                ],
                "artifacts": {"company": slug, "truncated": truncated},
            },
        )


__all__ = [
    "DesignExemplarInput",
    "DesignExemplarTool",
    "available_exemplars",
    "exemplars_root",
]
