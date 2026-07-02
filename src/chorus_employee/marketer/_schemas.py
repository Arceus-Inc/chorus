"""The Creative subagent's typed return contract (design doc §06, §10).

After Creative drafts a set of on-brand variants of Mira's seed post, it returns a
:class:`CreativeManifest` — the seed it varied plus one :class:`VariantEntry` per variant
(the variant's file, its angle, and whether ``brand_lint`` came back clean). Mira reads the
manifest to prune among the set and promote the strongest into ``content_draft.md``.

Two clean, dream-free value objects (frozen, slotted). :meth:`CreativeManifest.from_payload`
is the validating parser for the raw dict dream hands back (it raises ``ValueError`` on a
malformed payload — no silent defaults for required fields, no ``getattr`` gymnastics), and
:func:`creative_output_schema` is the JSON schema the subagent's ``output_schema`` enforces.
The schema is built field-by-field from these dataclasses and a drift test keeps the two in
lockstep, so a stringly JSON blob can never diverge from the typed shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VariantEntry:
    """One Creative variant — its file, its angle, and its self-lint result."""

    file: str  # worktree-relative path, e.g. "candidates/variant_01.md"
    angle: str  # a one-line description of this variant's angle/framing
    brand_lint_clean: bool  # did Creative's own brand_lint pass return zero findings?

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> VariantEntry:
        """Parse+validate one variant dict; raise ``ValueError`` on a malformed entry."""
        if not isinstance(payload, Mapping):
            raise ValueError("variant entry must be a mapping")
        file = _require_nonempty_str(payload, "file")
        angle = _require_nonempty_str(payload, "angle")
        clean = payload.get("brand_lint_clean")
        if not isinstance(clean, bool):
            raise ValueError("variant field 'brand_lint_clean' must be a boolean")
        return cls(file=file, angle=angle, brand_lint_clean=clean)


@dataclass(frozen=True, slots=True)
class CreativeManifest:
    """Creative's return value: the seed it varied plus the variants it produced."""

    seed: str  # the reference post Creative varied, e.g. "content_seed.md"
    variants: tuple[VariantEntry, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CreativeManifest:
        """Parse+validate the raw manifest dict; raise ``ValueError`` on malformed input."""
        if not isinstance(payload, Mapping):
            raise ValueError("creative manifest payload must be a mapping")
        seed = _require_nonempty_str(payload, "seed")
        raw_variants = payload.get("variants")
        if not isinstance(raw_variants, list):
            raise ValueError("manifest field 'variants' must be a list")
        variants = tuple(VariantEntry.from_payload(v) for v in raw_variants)
        return cls(seed=seed, variants=variants)


def _require_nonempty_str(payload: Mapping[str, Any], key: str) -> str:
    """Return ``payload[key]`` as a non-empty, stripped string or raise ``ValueError``."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"field {key!r} must be a non-empty string")
    return value.strip()


def creative_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Creative subagent's ``output_schema``.

    Built field-by-field from :class:`VariantEntry` / :class:`CreativeManifest`; the drift tests
    assert the schema's properties equal the dataclass fields, so the two cannot silently diverge.
    """
    variant_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "worktree-relative path to the variant file"},
            "angle": {
                "type": "string",
                "description": "one-line description of this variant's angle",
            },
            "brand_lint_clean": {
                "type": "boolean",
                "description": "true when Creative's brand_lint on this variant returned no findings",
            },
        },
        "required": ["file", "angle", "brand_lint_clean"],
    }
    return {
        "type": "object",
        "properties": {
            "seed": {"type": "string", "description": "the seed post Creative varied"},
            "variants": {
                "type": "array",
                "items": variant_schema,
                "description": "one entry per variant Creative drafted",
            },
        },
        "required": ["seed", "variants"],
    }


__all__ = ["CreativeManifest", "VariantEntry", "creative_output_schema"]
