"""Typed, immutable declarations for Arceus stack releases.

The package contains only domain models. It does not load manifests, access the
filesystem, resolve secret placeholders, or evaluate compatibility.
"""

from __future__ import annotations

from chorus.release._models import (
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
