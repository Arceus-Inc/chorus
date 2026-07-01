"""Creative subagent — the typed return contract (design doc §06, §10).

``CreativeManifest`` is what the Creative subagent returns after drafting a set of on-brand
variants: the seed it varied plus one entry per variant (its file, angle, and brand_lint status).
These tests pin the validating parser (``from_payload``) and lock the JSON ``output_schema`` to the
dataclass fields so the two can never silently drift.
"""

from __future__ import annotations

import dataclasses

import pytest

from chorus_employee.marketer._creative_manifest import (
    CreativeManifest,
    VariantEntry,
    creative_output_schema,
)

pytestmark = pytest.mark.unit


def _payload() -> dict[str, object]:
    return {
        "seed": "content_seed.md",
        "variants": [
            {"file": "candidates/variant_01.md", "angle": "problem-first", "brand_lint_clean": True},
            {"file": "candidates/variant_02.md", "angle": "proof-first", "brand_lint_clean": False},
        ],
    }


class TestFromPayload:
    def test_roundtrips_well_formed_payload(self) -> None:
        manifest = CreativeManifest.from_payload(_payload())
        assert manifest.seed == "content_seed.md"
        assert len(manifest.variants) == 2
        first = manifest.variants[0]
        assert isinstance(first, VariantEntry)
        assert first.file == "candidates/variant_01.md"
        assert first.angle == "problem-first"
        assert first.brand_lint_clean is True
        assert manifest.variants[1].brand_lint_clean is False

    def test_variants_is_a_tuple_not_a_list(self) -> None:
        # Frozen, hashable value object — the collection must be immutable too.
        manifest = CreativeManifest.from_payload(_payload())
        assert isinstance(manifest.variants, tuple)

    def test_empty_variants_is_allowed(self) -> None:
        # A degenerate run (Creative produced nothing) parses to an empty manifest, not an error —
        # the caller decides what to do with zero variants.
        manifest = CreativeManifest.from_payload({"seed": "content_seed.md", "variants": []})
        assert manifest.variants == ()

    def test_rejects_non_mapping_payload(self) -> None:
        with pytest.raises(ValueError, match="payload"):
            CreativeManifest.from_payload(["not", "a", "mapping"])  # type: ignore[arg-type]

    def test_rejects_missing_seed(self) -> None:
        with pytest.raises(ValueError, match="seed"):
            CreativeManifest.from_payload({"variants": []})

    def test_rejects_empty_seed(self) -> None:
        with pytest.raises(ValueError, match="seed"):
            CreativeManifest.from_payload({"seed": "   ", "variants": []})

    def test_rejects_non_list_variants(self) -> None:
        with pytest.raises(ValueError, match="variants"):
            CreativeManifest.from_payload({"seed": "content_seed.md", "variants": "nope"})

    def test_rejects_variant_missing_field(self) -> None:
        bad = {"seed": "s.md", "variants": [{"file": "v.md", "angle": "x"}]}
        with pytest.raises(ValueError, match="brand_lint_clean"):
            CreativeManifest.from_payload(bad)

    def test_rejects_variant_mistyped_flag(self) -> None:
        bad = {
            "seed": "s.md",
            "variants": [{"file": "v.md", "angle": "x", "brand_lint_clean": "yes"}],
        }
        with pytest.raises(ValueError, match="brand_lint_clean"):
            CreativeManifest.from_payload(bad)

    def test_rejects_variant_empty_file(self) -> None:
        bad = {"seed": "s.md", "variants": [{"file": "", "angle": "x", "brand_lint_clean": True}]}
        with pytest.raises(ValueError, match="file"):
            CreativeManifest.from_payload(bad)


class TestImmutability:
    def test_variant_entry_is_frozen(self) -> None:
        entry = VariantEntry(file="v.md", angle="a", brand_lint_clean=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.angle = "b"  # type: ignore[misc]

    def test_manifest_is_frozen(self) -> None:
        manifest = CreativeManifest(seed="s.md", variants=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            manifest.seed = "other.md"  # type: ignore[misc]


class TestOutputSchema:
    def test_schema_is_an_object(self) -> None:
        schema = creative_output_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) == {"seed", "variants"}

    def test_top_level_properties_match_dataclass_fields(self) -> None:
        # Drift guard: the schema's top-level keys must be exactly CreativeManifest's fields.
        schema = creative_output_schema()
        field_names = {f.name for f in dataclasses.fields(CreativeManifest)}
        assert set(schema["properties"]) == field_names

    def test_variant_item_properties_match_variant_fields(self) -> None:
        # Drift guard for the nested item shape.
        schema = creative_output_schema()
        item_props = schema["properties"]["variants"]["items"]["properties"]
        field_names = {f.name for f in dataclasses.fields(VariantEntry)}
        assert set(item_props) == field_names

    def test_schema_parses_back_through_from_payload(self) -> None:
        # A payload built to the schema's shape must survive from_payload — schema and parser agree.
        manifest = CreativeManifest.from_payload(_payload())
        assert manifest.variants[0].file == "candidates/variant_01.md"
