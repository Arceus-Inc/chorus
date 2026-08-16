"""Release manifest domain-model contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from chorus.release import (
    CompatibilityBound,
    CompatibilityBoundKind,
    CompatibilityRequirement,
    ComponentPin,
    PackageVersion,
    ReleaseComponent,
    ReleaseManifest,
    SecretPlaceholder,
    SourceRevision,
    WorkProductKind,
    WorkProductReference,
)

pytestmark = pytest.mark.unit


def _revision(character: str) -> SourceRevision:
    return SourceRevision(commit=character * 40)


def _pin(component: ReleaseComponent, character: str) -> ComponentPin:
    return ComponentPin(
        component=component,
        package=component.package_name,
        version=PackageVersion(major=1, minor=2, patch=3),
        source_revision=_revision(character),
    )


def _all_pins() -> tuple[ComponentPin, ...]:
    return (
        _pin(ReleaseComponent.DREAM, "a"),
        _pin(ReleaseComponent.CHORUS, "b"),
        _pin(ReleaseComponent.LATTICE, "c"),
        _pin(ReleaseComponent.HORIZON, "d"),
        _pin(ReleaseComponent.PODIUM, "e"),
    )


def _manifest(*, release_name: str = "wave-12") -> ReleaseManifest:
    return ReleaseManifest(
        manifest_version=1,
        release_name=release_name,
        components=_all_pins(),
    )


def test_manifest_is_canonical_immutable_and_fully_typed() -> None:
    manifest = ReleaseManifest(
        manifest_version=1,
        release_name="2026.08.09",
        components=tuple(reversed(_all_pins())),
        compatibility_requirements=(
            CompatibilityRequirement(
                consumer=ReleaseComponent.PODIUM,
                provider=ReleaseComponent.CHORUS,
                bounds=(
                    CompatibilityBound(
                        kind=CompatibilityBoundKind.AT_LEAST,
                        version=PackageVersion(major=1, minor=2, patch=0),
                    ),
                    CompatibilityBound(
                        kind=CompatibilityBoundKind.AT_MOST,
                        version=PackageVersion(major=1, minor=9, patch=0),
                    ),
                ),
            ),
        ),
        work_products=(
            WorkProductReference(
                component=ReleaseComponent.CHORUS,
                kind=WorkProductKind.PACKAGE,
                reference="pkg:pypi/chorus@1.2.3",
            ),
        ),
        secret_placeholders=(SecretPlaceholder(name="OPENAI_API_KEY"),),
    )

    assert manifest.components == _all_pins()
    assert manifest.compatibility_requirements[0].provider is ReleaseComponent.CHORUS
    assert manifest.components[0].source_revision.commit == "a" * 40
    assert manifest.secret_placeholders == (SecretPlaceholder(name="OPENAI_API_KEY"),)
    with pytest.raises(FrozenInstanceError):
        manifest.release_name = "other"  # type: ignore[misc]


def test_source_revision_normalizes_uppercase_commit_sha() -> None:
    uppercase = SourceRevision(commit="ABCDEF1234" * 4)
    lowercase = SourceRevision(commit="abcdef1234" * 4)

    assert uppercase.commit == "abcdef1234" * 4
    assert uppercase == lowercase
    assert hash(uppercase) == hash(lowercase)


def test_component_pin_requires_its_canonical_package() -> None:
    with pytest.raises(ValueError, match="package"):
        ComponentPin(
            component=ReleaseComponent.CHORUS,
            package="chorus-sdk",
            version=PackageVersion(major=1, minor=0, patch=0),
            source_revision=_revision("a"),
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: PackageVersion(major=-1, minor=0, patch=0), "non-negative"),
        (lambda: SourceRevision(commit="main"), "full git commit"),
        (lambda: SecretPlaceholder(name=" "), "blank"),
        (
            lambda: WorkProductReference(
                component=ReleaseComponent.DREAM,
                kind=WorkProductKind.PACKAGE,
                reference=" ",
            ),
            "blank",
        ),
    ],
)
def test_value_objects_reject_blank_or_non_immutable_values(
    factory: Callable[[], object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_compatibility_rejects_unsupported_and_contradictory_bounds() -> None:
    version = PackageVersion(major=1, minor=0, patch=0)
    with pytest.raises(ValueError, match="unsupported"):
        CompatibilityBound(kind="greater_than", version=version)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="self"):
        CompatibilityRequirement(
            consumer=ReleaseComponent.CHORUS,
            provider=ReleaseComponent.CHORUS,
            bounds=(CompatibilityBound(CompatibilityBoundKind.AT_LEAST, version),),
        )
    with pytest.raises(ValueError, match="contradictory"):
        CompatibilityRequirement(
            consumer=ReleaseComponent.PODIUM,
            provider=ReleaseComponent.CHORUS,
            bounds=(
                CompatibilityBound(
                    CompatibilityBoundKind.AT_LEAST,
                    PackageVersion(major=2, minor=0, patch=0),
                ),
                CompatibilityBound(
                    CompatibilityBoundKind.AT_MOST,
                    PackageVersion(major=1, minor=9, patch=0),
                ),
            ),
        )
    with pytest.raises(ValueError, match="exact"):
        CompatibilityRequirement(
            consumer=ReleaseComponent.PODIUM,
            provider=ReleaseComponent.CHORUS,
            bounds=(
                CompatibilityBound(CompatibilityBoundKind.EXACT, version),
                CompatibilityBound(CompatibilityBoundKind.AT_LEAST, version),
            ),
        )


def test_manifest_rejects_missing_components_duplicates_and_mutable_collections() -> None:
    pins = _all_pins()
    with pytest.raises(ValueError, match="all required"):
        ReleaseManifest(
            manifest_version=1,
            release_name="wave-12",
            components=pins[:-1],
        )
    with pytest.raises(ValueError, match="duplicate"):
        ReleaseManifest(
            manifest_version=1,
            release_name="wave-12",
            components=(*pins[:-1], pins[0], pins[-1]),
        )
    with pytest.raises(ValueError, match="tuple"):
        ReleaseManifest(
            manifest_version=1,
            release_name="wave-12",
            components=list(pins),  # type: ignore[arg-type]
        )


def test_manifest_rejects_duplicate_relations_products_and_secret_material() -> None:
    pins = _all_pins()
    requirement = CompatibilityRequirement(
        consumer=ReleaseComponent.PODIUM,
        provider=ReleaseComponent.CHORUS,
        bounds=(
            CompatibilityBound(
                CompatibilityBoundKind.AT_LEAST,
                PackageVersion(major=1, minor=0, patch=0),
            ),
        ),
    )
    product = WorkProductReference(
        component=ReleaseComponent.CHORUS,
        kind=WorkProductKind.PACKAGE,
        reference="pkg:pypi/chorus@1.2.3",
    )
    with pytest.raises(ValueError, match="duplicate compatibility"):
        ReleaseManifest(
            manifest_version=1,
            release_name="wave-12",
            components=pins,
            compatibility_requirements=(requirement, requirement),
        )
    with pytest.raises(ValueError, match="duplicate work product"):
        ReleaseManifest(
            manifest_version=1,
            release_name="wave-12",
            components=pins,
            work_products=(product, product),
        )
    with pytest.raises(ValueError, match="secret material"):
        SecretPlaceholder(name="OPENAI_API_KEY=sk-live-secret")
    with pytest.raises(TypeError):
        SecretPlaceholder(name="OPENAI_API_KEY", value="sk-live-secret")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "secret_material",
    (
        "OPENAI_API_KEY=sk-live-secret",
        "artifact?token=cleartext-token",
        "Bearer cleartext-token",
        "https://release-bot:cleartext-password@example.invalid/artifact",
    ),
)
def test_persisted_strings_reject_obvious_secret_material(secret_material: str) -> None:
    with pytest.raises(ValueError, match="obvious secret material"):
        WorkProductReference(
            component=ReleaseComponent.CHORUS,
            kind=WorkProductKind.PACKAGE,
            reference=secret_material,
        )
    with pytest.raises(ValueError, match="obvious secret material"):
        _manifest(release_name=secret_material)
    with pytest.raises(ValueError, match="obvious secret material"):
        SecretPlaceholder(name=secret_material)


@pytest.mark.parametrize(
    "reference",
    (
        "pkg:pypi/chorus@1.2.3",
        "ghcr.io/arceus/chorus:1.2.3",
        f"ghcr.io/arceus/chorus@sha256:{'a' * 64}",
        "pkg:generic/sk-runtime@1.2.3",
        "ghcr.io/arceus/sk-runtime:1.2.3",
    ),
)
def test_work_product_reference_accepts_release_coordinates(reference: str) -> None:
    product = WorkProductReference(
        component=ReleaseComponent.CHORUS,
        kind=WorkProductKind.PACKAGE,
        reference=reference,
    )

    assert product.reference == reference


@pytest.mark.parametrize(
    "secret_material",
    (
        f"sk-{'a' * 48}",
        f"sk-proj-{'a' * 48}",
        f"ghp_{'a' * 36}",
        f"github_pat_{'a' * 82}",
    ),
)
def test_persisted_strings_reject_credential_shaped_bare_tokens(secret_material: str) -> None:
    with pytest.raises(ValueError, match="obvious secret material"):
        WorkProductReference(
            component=ReleaseComponent.CHORUS,
            kind=WorkProductKind.PACKAGE,
            reference=secret_material,
        )


@pytest.mark.parametrize(
    ("prefix", "body_length"),
    (
        ("ghp_", 36),
        ("gho_", 36),
        ("ghu_", 36),
        ("ghs_", 36),
        ("ghr_", 36),
        ("github_pat_", 82),
    ),
)
def test_persisted_strings_reject_github_tokens_with_underscore_bodies(
    prefix: str, body_length: int
) -> None:
    left_length = body_length // 2
    secret_material = f"{prefix}{'a' * left_length}_{'b' * (body_length - left_length - 1)}"

    with pytest.raises(ValueError, match="obvious secret material"):
        WorkProductReference(
            component=ReleaseComponent.CHORUS,
            kind=WorkProductKind.PACKAGE,
            reference=secret_material,
        )
