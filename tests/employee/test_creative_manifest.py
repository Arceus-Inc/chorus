"""Creative subagent — the typed return contract (design doc §06, §10).

``CreativeManifest`` is a pydantic model: what the Creative subagent returns after drafting a set of
on-brand variants (the seed it varied plus one entry per variant — its file, angle, and brand_lint
status). ``model_validate`` parses+validates the raw return; ``creative_output_schema`` is the JSON
schema DERIVED from the model (single source, no drift with the hand-written schema).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chorus_employee.marketer._subagents._creative._schema import (
    CreativeManifest,
    VariantEntry,
    creative_output_schema,
)

pytestmark = pytest.mark.unit


def _payload() -> dict[str, object]:
    return {
        "seed": "content_seed.md",
        "variants": [
            {
                "file": "candidates/variant_01.md",
                "angle": "problem-first",
                "brand_lint_clean": True,
            },
            {"file": "candidates/variant_02.md", "angle": "proof-first", "brand_lint_clean": False},
        ],
    }


class TestModelValidate:
    def test_roundtrips_well_formed_payload(self) -> None:
        manifest = CreativeManifest.model_validate(_payload())
        assert manifest.seed == "content_seed.md"
        assert len(manifest.variants) == 2
        first = manifest.variants[0]
        assert isinstance(first, VariantEntry)
        assert first.file == "candidates/variant_01.md"
        assert first.angle == "problem-first"
        assert first.brand_lint_clean is True
        assert manifest.variants[1].brand_lint_clean is False

    def test_empty_variants_is_allowed(self) -> None:
        # A degenerate run (Creative produced nothing) parses to an empty manifest, not an error —
        # the caller decides what to do with zero variants.
        manifest = CreativeManifest.model_validate({"seed": "content_seed.md", "variants": []})
        assert manifest.variants == []

    def test_rejects_missing_seed(self) -> None:
        with pytest.raises(ValidationError, match="seed"):
            CreativeManifest.model_validate({"variants": []})

    def test_rejects_blank_seed(self) -> None:
        # str_strip_whitespace + min_length=1: a whitespace-only seed collapses to empty and fails.
        with pytest.raises(ValidationError, match="seed"):
            CreativeManifest.model_validate({"seed": "   ", "variants": []})

    def test_rejects_missing_variants(self) -> None:
        with pytest.raises(ValidationError, match="variants"):
            CreativeManifest.model_validate({"seed": "content_seed.md"})

    def test_rejects_non_list_variants(self) -> None:
        with pytest.raises(ValidationError, match="variants"):
            CreativeManifest.model_validate({"seed": "content_seed.md", "variants": "nope"})

    def test_rejects_variant_missing_field(self) -> None:
        bad = {"seed": "s.md", "variants": [{"file": "v.md", "angle": "x"}]}
        with pytest.raises(ValidationError, match="brand_lint_clean"):
            CreativeManifest.model_validate(bad)

    def test_rejects_variant_mistyped_flag(self) -> None:
        # strict=True on the bool: a stringly flag is an error, never silently coerced to True.
        bad = {
            "seed": "s.md",
            "variants": [{"file": "v.md", "angle": "x", "brand_lint_clean": "yes"}],
        }
        with pytest.raises(ValidationError, match="brand_lint_clean"):
            CreativeManifest.model_validate(bad)

    def test_rejects_variant_empty_file(self) -> None:
        bad = {"seed": "s.md", "variants": [{"file": "", "angle": "x", "brand_lint_clean": True}]}
        with pytest.raises(ValidationError, match="file"):
            CreativeManifest.model_validate(bad)


class TestOutputSchema:
    def test_schema_is_derived_from_the_model(self) -> None:
        # Single source of truth: the exported schema IS the model's json schema — nothing to drift.
        assert creative_output_schema() == CreativeManifest.model_json_schema()

    def test_schema_is_an_object_requiring_seed_and_variants(self) -> None:
        schema = creative_output_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) == {"seed", "variants"}

    def test_model_fields_are_the_contract(self) -> None:
        assert set(CreativeManifest.model_fields) == {"seed", "variants"}
        assert set(VariantEntry.model_fields) == {"file", "angle", "brand_lint_clean"}
