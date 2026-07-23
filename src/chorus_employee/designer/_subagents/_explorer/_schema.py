"""The Explorer subagent's typed return contract (designer §06, §10).

After the Explorer drafts a set of on-system variants of the Designer's seed, it returns an
:class:`ExplorerManifest` — the seed it varied plus one :class:`VariantEntry` per variant (the
variant's file, its approach, and whether ``design_lint`` came back clean). The Designer reads the
manifest to prune among the set and promote the strongest into ``design_spec.md``.

Pydantic models are the single source of truth (mirroring the Creative's contract):
:func:`explorer_output_schema` *derives* the JSON schema the subagent's ``output_schema`` enforces
via :meth:`~pydantic.BaseModel.model_json_schema` (dream's ``jsonschema`` validator resolves its
``$ref``/``$defs``), and a caller parses the raw return with :meth:`ExplorerManifest.model_validate`
— no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VariantEntry(BaseModel):
    """One Explorer variant — its file, its approach, and its self-lint result."""

    model_config = ConfigDict(str_strip_whitespace=True)

    file: str = Field(
        min_length=1,
        description="worktree-relative path to the variant file, e.g. variants/variant_01.md",
    )
    approach: str = Field(
        min_length=1,
        description="one-line description of this variant's layout/interaction approach",
    )
    rationale: str = Field(
        min_length=1,
        description=(
            "the design BET this variant makes and when it wins — the distinguishing axis (layout / "
            "hierarchy / interaction model / density) and the tradeoff it accepts, so the designer can "
            "make a reasoned selection rather than a coin flip"
        ),
    )
    design_lint_clean: bool = Field(
        strict=True,
        description="true when Explorer's design_lint on this variant returned no findings",
    )


class ExplorerManifest(BaseModel):
    """Explorer's return value: the seed it varied plus the variants it produced."""

    model_config = ConfigDict(str_strip_whitespace=True)

    seed: str = Field(
        min_length=1, description="the seed design Explorer varied, e.g. design_seed.md"
    )
    variants: list[VariantEntry] = Field(description="one entry per variant Explorer drafted")


def explorer_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Explorer subagent's ``output_schema`` — derived from the model."""
    return ExplorerManifest.model_json_schema()


__all__ = ["ExplorerManifest", "VariantEntry", "explorer_output_schema"]
