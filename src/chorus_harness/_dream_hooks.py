"""Dream lifecycle hooks Chorus registers at materialize (S1 #2 / #11 L1).

Hermes-aligned:
- PRE_TOOL_USE allow_block — dangerous command veto + evidence forge veto
- STOP allow_continue — evidence missing → nudge parent to spawn critic
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from dream.contracts.hook import HookEvent, HookResult, HookSpec

from chorus.roles._subagent import SubagentSpec

__all__ = [
    "DangerousToolVetoHook",
    "EvidenceContinueHook",
    "EvidenceForgeVetoHook",
    "EvidenceOwner",
    "EvidenceRequirement",
    "ProtectedEvidencePath",
    "StopHookPhase",
    "StopHookRole",
    "register_employee_hooks",
]

_DANGEROUS_BASH = re.compile(
    r"(?:rm\s+-rf\s+/|mkfs\.|dd\s+if=.*of=/dev/|"
    r"curl\s+[^\n]*\|\s*(?:ba)?sh|wget\s+[^\n]*\|\s*(?:ba)?sh)",
    re.IGNORECASE,
)
_WRITE_TOOLS = frozenset({"write_file", "edit_file"})
_EVIDENCE_DIR = ".harness/subagent-evidence"


class StopHookRole(StrEnum):
    GENERATOR = "generator"


class StopHookPhase(StrEnum):
    PRE_SEAL = "pre_seal"


class EvidenceOwner(StrEnum):
    ANY_SPECIALIST = "__any_specialist__"


@dataclass(frozen=True)
class ProtectedEvidencePath:
    relative_path: str
    owner_subagent: str | EvidenceOwner


@dataclass(frozen=True)
class EvidenceRequirement:
    subagent_name: str
    relative_path: str
    claim: dict[str, object]


class DangerousToolVetoHook:
    """Block obviously destructive ``run_command`` invocations (Hermes pre_tool_call)."""

    spec = HookSpec(events=(HookEvent.PRE_TOOL_USE,), allow_block=True, priority=100)

    async def __call__(self, event: HookEvent, payload: dict[str, Any]) -> HookResult:
        if payload.get("tool_name") != "run_command":
            return HookResult()
        tool_input = payload.get("tool_input") or {}
        command = str(tool_input.get("command") or tool_input.get("cmd") or "")
        if command and _DANGEROUS_BASH.search(command):
            return HookResult(
                blocked=True,
                feedback=(
                    f"Blocked dangerous command pattern: {command[:160]!r}. "
                    "Use a safer scoped command inside the worktree."
                ),
            )
        return HookResult()


class EvidenceForgeVetoHook:
    """PRE_TOOL: parent cannot write Spec evidence paths — must spawn the specialist.

    Child sessions stamp ``subagent_name`` on the PRE payload and are allowed through
    so test_author / code_reviewer can still write their own artifacts.
    """

    def __init__(self, protected: tuple[ProtectedEvidencePath, ...]) -> None:
        self._protected = {
            _norm_rel(entry.relative_path): entry.owner_subagent for entry in protected
        }
        self.spec = HookSpec(events=(HookEvent.PRE_TOOL_USE,), allow_block=True, priority=90)

    async def __call__(self, event: HookEvent, payload: dict[str, Any]) -> HookResult:
        if payload.get("subagent_name"):
            return HookResult()  # specialist child writing its own evidence
        if payload.get("tool_name") not in _WRITE_TOOLS:
            return HookResult()
        tool_input = payload.get("tool_input") or {}
        rel = _norm_rel(str(tool_input.get("path") or ""))
        if not rel:
            return HookResult()
        owner = self._protected.get(rel)
        if owner is None and (rel == _EVIDENCE_DIR or rel.startswith(_EVIDENCE_DIR + "/")):
            owner = EvidenceOwner.ANY_SPECIALIST
        if owner is None:
            return HookResult()
        owner_label = (
            "the required specialist"
            if owner == EvidenceOwner.ANY_SPECIALIST
            else owner
        )
        return HookResult(
            blocked=True,
            feedback=(
                f"Do not forge evidence at {rel!r}. "
                f"Call spawn_subagent(subagent_type={owner_label!r}, goal=...) so provenance is recorded. "
                f"root_cause: evidence_forge; "
                f"safe_retry: spawn_subagent(subagent_type={owner_label!r}); "
                f"stop_condition: parent must not write specialist evidence paths."
            ),
        )


class EvidenceContinueHook:
    """STOP continue when required subagent evidence artifacts are missing (#11 L1)."""

    def __init__(
        self,
        requirements: tuple[EvidenceRequirement, ...],
        *,
        working_dir: Path,
    ) -> None:
        self._requirements = requirements
        self._working_dir = working_dir
        self.spec = HookSpec(events=(HookEvent.STOP,), allow_continue=True, priority=50)

    async def __call__(self, event: HookEvent, payload: dict[str, Any]) -> HookResult:
        if not self._requirements:
            return HookResult()
        # Planner/evaluator share the harness hooks; only nudge the craft generator.
        if payload.get("role") != StopHookRole.GENERATOR:
            return HookResult()
        if payload.get("phase") not in (None, StopHookPhase.PRE_SEAL):
            return HookResult()
        missing: list[str] = []
        for req in self._requirements:
            path = self._working_dir / req.relative_path
            if not _artifact_satisfies(path, req.claim):
                missing.append(req.subagent_name)
        if not missing:
            return HookResult()
        return HookResult(
            continue_message=(
                "Evidence incomplete for: "
                + ", ".join(missing)
                + ". Call spawn_subagent(subagent_type=<name>, goal=...) for each missing "
                "specialist before finishing this beat — do not write their verdict files yourself."
            )
        )


def register_employee_hooks(
    harness: Any,
    *,
    working_dir: Path,
    subagents: tuple[SubagentSpec, ...] = (),
) -> None:
    """Attach Chorus policy hooks to a dream Harness after ``build_harness``."""
    register = getattr(harness, "register_hook", None)
    if not callable(register):
        return  # stub harnesses in unit tests have no hook rail
    register(DangerousToolVetoHook())
    protected = tuple(
        ProtectedEvidencePath(spec.evidence_path, spec.name)
        for spec in subagents
        if spec.evidence_path is not None
    )
    if protected:
        register(EvidenceForgeVetoHook(protected))
    evidence = tuple(
        EvidenceRequirement(
            spec.name,
            spec.evidence_path,
            dict(spec.evidence_claim),
        )
        for spec in subagents
        if spec.evidence_path is not None and spec.evidence_claim is not None
    )
    if evidence:
        register(EvidenceContinueHook(evidence, working_dir=working_dir))


def _norm_rel(path: str) -> str:
    """Normalize a tool path to a repo-relative posix key (no leading ./)."""
    text = path.strip().replace("\\", "/")
    if not text:
        return ""
    # Drop absolute / worktree prefixes best-effort — tools usually pass relative paths.
    pure = PurePosixPath(text)
    parts = [p for p in pure.parts if p not in ("", ".")]
    while parts and parts[0] == "..":
        parts = parts[1:]
    return "/".join(parts)


def _artifact_satisfies(path: Path, claim: dict[str, object]) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    if not isinstance(data, dict):
        return False
    for key, expected in claim.items():
        if data.get(key) != expected:
            return False
    return True
