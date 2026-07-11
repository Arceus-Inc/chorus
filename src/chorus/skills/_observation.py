"""Harness-shaped observation returned by SkillManager / skill_manage tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillObservation:
    """Deterministic tool observation (agent-harness-construction contract)."""

    status: str  # success | warning | error
    summary: str
    next_actions: tuple[str, ...] = ()
    artifacts: dict[str, Any] = field(default_factory=dict)
    root_cause: str | None = None
    retry: str | None = None
    stop: str | None = None

    @classmethod
    def ok(
        cls,
        summary: str,
        *,
        artifacts: dict[str, Any] | None = None,
        next_actions: tuple[str, ...] | list[str] = (),
    ) -> SkillObservation:
        return cls(
            status="success",
            summary=summary,
            next_actions=tuple(next_actions),
            artifacts=dict(artifacts or {}),
        )

    @classmethod
    def error(
        cls,
        summary: str,
        *,
        root_cause: str,
        retry: str,
        stop: str,
        next_actions: tuple[str, ...] | list[str] = (),
        artifacts: dict[str, Any] | None = None,
    ) -> SkillObservation:
        return cls(
            status="error",
            summary=summary,
            next_actions=tuple(next_actions),
            artifacts=dict(artifacts or {}),
            root_cause=root_cause,
            retry=retry,
            stop=stop,
        )

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "summary": self.summary,
            "next_actions": list(self.next_actions),
            "artifacts": dict(self.artifacts),
        }
        if self.root_cause is not None:
            payload["root_cause"] = self.root_cause
        if self.retry is not None:
            payload["retry"] = self.retry
        if self.stop is not None:
            payload["stop"] = self.stop
        return payload


__all__ = ["SkillObservation"]
