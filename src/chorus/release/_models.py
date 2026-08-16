"""Immutable domain models for an Arceus stack release manifest.

This module deliberately models declarations only. Loading, serialising,
evaluating compatibility, and resolving secret placeholders belong to later
layers so a manifest stays deterministic, portable, and safe to inspect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ReleaseComponent(StrEnum):
    """The complete, fixed Arceus release stack."""

    DREAM = "dream"
    CHORUS = "chorus"
    LATTICE = "lattice"
    HORIZON = "horizon"
    PODIUM = "podium"

    @property
    def package_name(self) -> str:
        """The canonical distribution package for this component."""
        return self.value


_COMPONENT_ORDER: tuple[ReleaseComponent, ...] = (
    ReleaseComponent.DREAM,
    ReleaseComponent.CHORUS,
    ReleaseComponent.LATTICE,
    ReleaseComponent.HORIZON,
    ReleaseComponent.PODIUM,
)
_GIT_COMMIT = re.compile(r"[0-9a-fA-F]{40}")
_PLACEHOLDER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
_BARE_CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"sk-(?:[A-Za-z0-9]{32,}|proj-[A-Za-z0-9_-]{32,})"
    r"|gh[pousr]_[A-Za-z0-9_]{36}"
    r"|github_pat_[A-Za-z0-9_]{82}"
    r")(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_OBVIOUS_SECRET_MATERIAL: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|passwd|credential)"
        r"\s*=\s*[^&\s]+",
        re.IGNORECASE,
    ),
    re.compile(r"\bbearer\s+\S+", re.IGNORECASE),
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
    _BARE_CREDENTIAL,
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


@dataclass(frozen=True, slots=True, order=True)
class PackageVersion:
    """A pinned semantic package version, represented without a free-form range string."""

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        for name, value in (
            ("major", self.major),
            ("minor", self.minor),
            ("patch", self.patch),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"package version {name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class SourceRevision:
    """An immutable full Git commit identifier for a component source tree."""

    commit: str

    def __post_init__(self) -> None:
        if not isinstance(self.commit, str) or _GIT_COMMIT.fullmatch(self.commit) is None:
            raise ValueError("source revision must be a full git commit SHA")
        object.__setattr__(self, "commit", self.commit.lower())


@dataclass(frozen=True, slots=True)
class ComponentPin:
    """The exact package version and source revision selected for one component."""

    component: ReleaseComponent
    package: str
    version: PackageVersion
    source_revision: SourceRevision

    def __post_init__(self) -> None:
        _require_component(self.component, "component")
        _require_non_blank(self.package, "package")
        if self.package != self.component.package_name:
            raise ValueError(
                f"package {self.package!r} is not canonical for component {self.component.value!r}"
            )
        if not isinstance(self.version, PackageVersion):
            raise ValueError("component version must be a PackageVersion")
        if not isinstance(self.source_revision, SourceRevision):
            raise ValueError("component source revision must be a SourceRevision")


class CompatibilityBoundKind(StrEnum):
    """The supported inclusive compatibility bound operators."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    EXACT = "exact"


_BOUND_ORDER: tuple[CompatibilityBoundKind, ...] = (
    CompatibilityBoundKind.AT_LEAST,
    CompatibilityBoundKind.AT_MOST,
    CompatibilityBoundKind.EXACT,
)


@dataclass(frozen=True, slots=True)
class CompatibilityBound:
    """One typed, inclusive version bound; no range-expression parsing is involved."""

    kind: CompatibilityBoundKind
    version: PackageVersion

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CompatibilityBoundKind):
            raise ValueError(f"unsupported compatibility bound {self.kind!r}")
        if not isinstance(self.version, PackageVersion):
            raise ValueError("compatibility bound version must be a PackageVersion")


@dataclass(frozen=True, slots=True)
class CompatibilityRequirement:
    """A component's typed dependency on another component's package version."""

    consumer: ReleaseComponent
    provider: ReleaseComponent
    bounds: tuple[CompatibilityBound, ...]

    def __post_init__(self) -> None:
        _require_component(self.consumer, "compatibility consumer")
        _require_component(self.provider, "compatibility provider")
        if self.consumer is self.provider:
            raise ValueError("a component cannot declare a compatibility requirement on itself")
        _require_tuple(self.bounds, "compatibility bounds")
        if not self.bounds:
            raise ValueError("compatibility requirements require at least one bound")
        if not all(isinstance(bound, CompatibilityBound) for bound in self.bounds):
            raise ValueError("compatibility bounds must contain CompatibilityBound values")

        kinds = tuple(bound.kind for bound in self.bounds)
        if len(set(kinds)) != len(kinds):
            raise ValueError("duplicate compatibility bounds are not supported")
        exact = _bound_for(self.bounds, CompatibilityBoundKind.EXACT)
        if exact is not None and len(self.bounds) != 1:
            raise ValueError("an exact compatibility bound cannot be combined with other bounds")
        lower = _bound_for(self.bounds, CompatibilityBoundKind.AT_LEAST)
        upper = _bound_for(self.bounds, CompatibilityBoundKind.AT_MOST)
        if lower is not None and upper is not None and lower.version > upper.version:
            raise ValueError("compatibility bounds are contradictory")

        object.__setattr__(self, "bounds", _canonical_bounds(self.bounds))


class WorkProductKind(StrEnum):
    """The supported release work-product classes."""

    PACKAGE = "package"
    CONTAINER_IMAGE = "container_image"
    DEPLOYMENT_BUNDLE = "deployment_bundle"
    SBOM = "sbom"
    PROVENANCE = "provenance"
    RELEASE_NOTES = "release_notes"


@dataclass(frozen=True, slots=True)
class WorkProductReference:
    """A typed reference to one component-owned, externally materialised work product."""

    component: ReleaseComponent
    kind: WorkProductKind
    reference: str

    def __post_init__(self) -> None:
        _require_component(self.component, "work product component")
        if not isinstance(self.kind, WorkProductKind):
            raise ValueError(f"unsupported work product kind {self.kind!r}")
        _require_safe_to_persist(self.reference, "work product reference")


@dataclass(frozen=True, slots=True)
class SecretPlaceholder:
    """A named secret slot; it intentionally has no field that could carry a secret value."""

    name: str

    def __post_init__(self) -> None:
        _require_safe_to_persist(self.name, "secret placeholder name")
        if _PLACEHOLDER_NAME.fullmatch(self.name) is None:
            raise ValueError("secret placeholder name must be an identifier, never a secret value")


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """A complete, canonical, versioned release declaration for the five-component stack."""

    manifest_version: int
    release_name: str
    components: tuple[ComponentPin, ...]
    compatibility_requirements: tuple[CompatibilityRequirement, ...] = ()
    work_products: tuple[WorkProductReference, ...] = ()
    secret_placeholders: tuple[SecretPlaceholder, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.manifest_version, bool)
            or not isinstance(self.manifest_version, int)
            or self.manifest_version < 1
        ):
            raise ValueError("manifest version must be a positive integer")
        _require_safe_to_persist(self.release_name, "release name")
        _require_tuple(self.components, "components")
        _require_tuple(self.compatibility_requirements, "compatibility requirements")
        _require_tuple(self.work_products, "work products")
        _require_tuple(self.secret_placeholders, "secret placeholders")
        if not all(isinstance(pin, ComponentPin) for pin in self.components):
            raise ValueError("components must contain ComponentPin values")
        if not all(
            isinstance(requirement, CompatibilityRequirement)
            for requirement in self.compatibility_requirements
        ):
            raise ValueError(
                "compatibility requirements must contain CompatibilityRequirement values"
            )
        if not all(isinstance(product, WorkProductReference) for product in self.work_products):
            raise ValueError("work products must contain WorkProductReference values")
        if not all(
            isinstance(placeholder, SecretPlaceholder) for placeholder in self.secret_placeholders
        ):
            raise ValueError("secret placeholders must contain SecretPlaceholder values")

        component_ids = tuple(pin.component for pin in self.components)
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("duplicate component pins are not supported")
        if set(component_ids) != set(_COMPONENT_ORDER):
            raise ValueError("a release manifest must pin all required components exactly once")
        _require_unique(
            tuple(
                (requirement.consumer, requirement.provider)
                for requirement in self.compatibility_requirements
            ),
            "duplicate compatibility requirements are not supported",
        )
        _require_unique(
            tuple((product.component, product.kind) for product in self.work_products),
            "duplicate work products are not supported",
        )
        _require_unique(
            tuple(placeholder.name for placeholder in self.secret_placeholders),
            "duplicate secret placeholders are not supported",
        )

        object.__setattr__(self, "components", _canonical_components(self.components))
        object.__setattr__(
            self,
            "compatibility_requirements",
            _canonical_requirements(self.compatibility_requirements),
        )
        object.__setattr__(self, "work_products", _canonical_work_products(self.work_products))
        object.__setattr__(
            self,
            "secret_placeholders",
            tuple(sorted(self.secret_placeholders, key=lambda placeholder: placeholder.name)),
        )


def _require_component(component: ReleaseComponent, field_name: str) -> None:
    if not isinstance(component, ReleaseComponent):
        raise ValueError(f"{field_name} must be a ReleaseComponent")


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _require_safe_to_persist(value: str, field_name: str) -> None:
    """Reject unmistakable inline secrets as defense-in-depth, not comprehensive scanning."""
    _require_non_blank(value, field_name)
    if any(pattern.search(value) is not None for pattern in _OBVIOUS_SECRET_MATERIAL):
        raise ValueError(f"{field_name} contains obvious secret material")


def _require_tuple(value: object, field_name: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a tuple")


def _require_unique(values: tuple[object, ...], message: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(message)


def _bound_for(
    bounds: tuple[CompatibilityBound, ...], kind: CompatibilityBoundKind
) -> CompatibilityBound | None:
    return next((bound for bound in bounds if bound.kind is kind), None)


def _component_rank(component: ReleaseComponent) -> int:
    return _COMPONENT_ORDER.index(component)


def _canonical_components(components: tuple[ComponentPin, ...]) -> tuple[ComponentPin, ...]:
    return tuple(sorted(components, key=lambda pin: _component_rank(pin.component)))


def _canonical_bounds(
    bounds: tuple[CompatibilityBound, ...],
) -> tuple[CompatibilityBound, ...]:
    return tuple(sorted(bounds, key=lambda bound: _BOUND_ORDER.index(bound.kind)))


def _canonical_requirements(
    requirements: tuple[CompatibilityRequirement, ...],
) -> tuple[CompatibilityRequirement, ...]:
    return tuple(
        sorted(
            requirements,
            key=lambda requirement: (
                _component_rank(requirement.consumer),
                _component_rank(requirement.provider),
            ),
        )
    )


def _canonical_work_products(
    work_products: tuple[WorkProductReference, ...],
) -> tuple[WorkProductReference, ...]:
    return tuple(
        sorted(
            work_products,
            key=lambda product: (
                _component_rank(product.component),
                product.kind.value,
                product.reference,
            ),
        )
    )


__all__ = [
    "CompatibilityBound",
    "CompatibilityBoundKind",
    "CompatibilityRequirement",
    "ComponentPin",
    "PackageVersion",
    "ReleaseComponent",
    "ReleaseManifest",
    "SecretPlaceholder",
    "SourceRevision",
    "WorkProductKind",
    "WorkProductReference",
]
