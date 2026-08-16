"""Immutable harness-input snapshots pinned to an agent configuration revision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _require_nonblank(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")


@dataclass(frozen=True)
class AgentIdentity:
    """The stable identity whose configuration is being versioned."""

    value: str

    def __post_init__(self) -> None:
        _require_nonblank(self.value, "agent identity")


@dataclass(frozen=True)
class AgentsMdReference:
    """The exact AGENTS.md revision and content supplied to the harness."""

    revision: str
    content: str

    def __post_init__(self) -> None:
        _require_nonblank(self.revision, "AGENTS.md revision")


@dataclass(frozen=True)
class ProviderModelConfig:
    """The provider/model pair selected for a harness execution."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        _require_nonblank(self.provider, "provider")
        _require_nonblank(self.model, "model")


@dataclass(frozen=True)
class SandboxProfile:
    """The named sandbox profile supplied to the harness."""

    value: str

    def __post_init__(self) -> None:
        _require_nonblank(self.value, "sandbox profile")


@dataclass(frozen=True)
class SkillRevisionPin:
    """One immutable skill revision included in the effective skill set."""

    skill_revision_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.skill_revision_id, "skill revision pin")


@dataclass(frozen=True)
class EffectiveToolPin:
    """One resolved tool and the source that made it effective."""

    identifier: str
    provenance: str

    def __post_init__(self) -> None:
        _require_nonblank(self.identifier, "effective tool identifier")
        _require_nonblank(self.provenance, "effective tool provenance")


@dataclass(frozen=True)
class AgentConfigRevision:
    """Immutable pins for the versioned harness inputs selected for one agent run."""

    id: str
    agent: AgentIdentity
    revision_no: int
    agents_md: AgentsMdReference
    provider_model: ProviderModelConfig
    sandbox_profile: SandboxProfile
    skill_pins: tuple[SkillRevisionPin, ...] = ()
    tool_pins: tuple[EffectiveToolPin, ...] = ()
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.id, "agent config revision id")
        if self.revision_no <= 0:
            raise ValueError("agent config revision number must be positive")
        if len(self.skill_pins) != len(set(self.skill_pins)):
            raise ValueError("skill pins must not contain duplicates")
        if len(self.tool_pins) != len({pin.identifier for pin in self.tool_pins}):
            raise ValueError("effective tool pins must not contain duplicates")


__all__ = [
    "AgentConfigRevision",
    "AgentIdentity",
    "AgentsMdReference",
    "EffectiveToolPin",
    "ProviderModelConfig",
    "SandboxProfile",
    "SkillRevisionPin",
]
