"""The Creative subagent's typed return contract (design doc §06, §10).

After Creative drafts a set of on-brand variants of Mira's seed post, it returns a
:class:`CreativeManifest` — the seed it varied plus one :class:`VariantEntry` per variant
(the variant's file, its angle, and whether ``brand_lint`` came back clean). Mira reads the
manifest to prune among the set and promote the strongest into ``content_draft.md``.

Pydantic models, mirroring the Web-Research Orchestrator's contract: the models are the single
source of truth. :func:`creative_output_schema` *derives* the JSON schema the subagent's
``output_schema`` enforces via :meth:`~pydantic.BaseModel.model_json_schema` (dream's
``jsonschema`` validator resolves its ``$ref``/``$defs``), and a caller parses the raw return
with :meth:`CreativeManifest.model_validate` — no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VariantEntry(BaseModel):
    """One Creative variant — its file, its angle, and its self-lint result."""

    model_config = ConfigDict(str_strip_whitespace=True)

    file: str = Field(
        min_length=1,
        description="worktree-relative path to the variant file, e.g. candidates/variant_01.md",
    )
    angle: str = Field(
        min_length=1, description="one-line description of this variant's angle/framing"
    )
    brand_lint_clean: bool = Field(
        strict=True,
        description="true when Creative's brand_lint on this variant returned no findings",
    )


class CreativeManifest(BaseModel):
    """Creative's return value: the seed it varied plus the variants it produced."""

    model_config = ConfigDict(str_strip_whitespace=True)

    seed: str = Field(
        min_length=1, description="the seed post Creative varied, e.g. content_seed.md"
    )
    variants: list[VariantEntry] = Field(description="one entry per variant Creative drafted")


def creative_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Creative subagent's ``output_schema`` — derived from the model."""
    return CreativeManifest.model_json_schema()


__all__ = ["CreativeManifest", "VariantEntry", "creative_output_schema"]
