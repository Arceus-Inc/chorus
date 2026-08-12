"""Dream lifecycle hooks Chorus registers at materialize (S1 #2 / #11 L1).

Hermes-aligned:
- PRE_TOOL_USE allow_block — dangerous command veto + evidence forge veto
- STOP allow_continue — evidence missing → nudge parent to spawn critic
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from dream.contracts.hook import HookEvent, HookResult, HookSpec
from dream.state.shadow import (
    ShadowCheckpointConfig,
    ShadowCheckpointHook,
    ShadowCheckpointManager,
    ShadowCheckpointStore,
)

from chorus.context import ContextAudience, TaskContextPacket, render_task_context
from chorus.roles._subagent import SubagentSpec

__all__ = [
    "DangerousToolVetoHook",
    "EvidenceContinueHook",
    "EvidenceForgeVetoHook",
    "EvidenceOwner",
    "EvidenceRequirement",
    "ProtectedEvidencePath",
    "ShadowCheckpointHook",
    "StopHookPhase",
    "StopHookRole",
    "VolatileBeatPacket",
    "VolatileBeatPacketHook",
    "register_employee_hooks",
]

_DANGEROUS_BASH = re.compile(
    r"(?:rm\s+-rf\s+/(?:\s|$|\*|[;&|])|mkfs\.|dd\s+if=.*of=/dev/|"
    r"curl\s+[^\n]*\|\s*(?:ba)?sh|wget\s+[^\n]*\|\s*(?:ba)?sh)",
    re.IGNORECASE,
)
_WRITE_TOOLS = frozenset({"write_file", "edit_file", "apply_patch"})
_DIRECT_PATH_WRITE_TOOLS = frozenset({"write_file", "edit_file"})
_EVIDENCE_DIR = ".harness/subagent-evidence"
_PATCH_FILE_TARGET = re.compile(
    r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+?)\s*$", re.MULTILINE
)


class StopHookRole(StrEnum):
    GENERATOR = "generator"


class StopHookPhase(StrEnum):
    PRE_SEAL = "pre_seal"


class EvidenceOwner(StrEnum):
    ANY_SPECIALIST = "__any_specialist__"


@dataclass(frozen=True)
class VolatileBeatPacket:
    """Changing beat facts injected as user context, outside the stable prompt."""

    task_context: TaskContextPacket | None = None
    on_injected: Callable[[], None] | None = None

    def render(self, audience: ContextAudience | None) -> str:
        if audience is None or self.task_context is None:
            return ""
        return render_task_context(self.task_context, audience)


class VolatileBeatPacketHook:
    spec = HookSpec(events=(HookEvent.USER_PROMPT_SUBMIT,), priority=80)

    def __init__(self, packet: VolatileBeatPacket) -> None:
        self._packet = packet
        self._consumed = False

    async def __call__(self, event: HookEvent, payload: dict[str, Any]) -> HookResult:
        audience = _audience_for(payload.get("role"))
        content = self._packet.render(audience)
        if not content:
            return HookResult()
        if audience is ContextAudience.GENERATOR and not self._consumed:
            self._consumed = True
            if self._packet.on_injected is not None:
                self._packet.on_injected()
        return HookResult(inject_context=content)


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

    def __init__(self, protected: tuple[ProtectedEvidencePath, ...], *, working_dir: Path) -> None:
        self._working_dir = working_dir.resolve()
        self._protected = {
            _norm_rel(entry.relative_path): entry.owner_subagent for entry in protected
        }
        self.spec = HookSpec(events=(HookEvent.PRE_TOOL_USE,), allow_block=True, priority=90)

    async def __call__(self, event: HookEvent, payload: dict[str, Any]) -> HookResult:
        if payload.get("subagent_name"):
            return HookResult()  # specialist child writing its own evidence
        tool_name = payload.get("tool_name")
        if tool_name not in _WRITE_TOOLS and tool_name != "run_command":
            return HookResult()
        tool_input = payload.get("tool_input") or {}
        for path in _write_paths(tool_name, tool_input):
            rel = _norm_rel(path, self._working_dir)
            if not rel:
                continue
            owner = self._protected.get(rel)
            if owner is None and (rel == _EVIDENCE_DIR or rel.startswith(_EVIDENCE_DIR + "/")):
                owner = EvidenceOwner.ANY_SPECIALIST
            if owner is None:
                continue
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
        return HookResult()


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
    stop_evidence_requirements: bool = False,
    volatile_packet: VolatileBeatPacket | None = None,
) -> None:
    """Attach Chorus policy hooks to a dream Harness after ``build_harness``.

    By default registers forge veto only (not STOP continue). EvidenceContinue
    nudges spawn when Spec claims are missing — opt in when a beat DoD requires it.
    """
    register = getattr(harness, "register_hook", None)
    if not callable(register):
        return  # stub harnesses in unit tests have no hook rail
    register(DangerousToolVetoHook())
    register(
        ShadowCheckpointHook(
            manager=ShadowCheckpointManager(
                store=ShadowCheckpointStore(base_dir=_shadow_checkpoint_base(working_dir)),
                config=ShadowCheckpointConfig(enabled=True),
            ),
            working_dir=working_dir,
        )
    )
    if volatile_packet is not None and volatile_packet.task_context is not None:
        register(VolatileBeatPacketHook(volatile_packet))
    protected = tuple(
        ProtectedEvidencePath(spec.evidence_path, spec.name)
        for spec in subagents
        if spec.evidence_path is not None
    )
    if protected:
        register(EvidenceForgeVetoHook(protected, working_dir=working_dir))
    if not stop_evidence_requirements:
        return
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


def _write_paths(tool_name: object, tool_input: Mapping[str, object]) -> tuple[str, ...]:
    """Return every repository path a mutation tool declares."""
    if tool_name in _DIRECT_PATH_WRITE_TOOLS:
        return (str(tool_input.get("path") or ""),)
    if tool_name == "apply_patch":
        return tuple(match.group(1) for match in _PATCH_FILE_TARGET.finditer(str(tool_input.get("patch") or "")))
    return tuple(
        match.group(1)
        for match in re.finditer(
            r"(?:>>?|\|\s*tee\s+)\s*[\"']?([^\"'\s;|&]+)",
            str(tool_input.get("command") or tool_input.get("cmd") or ""),
        )
    )


def _norm_rel(path: str, working_dir: Path | None = None) -> str:
    """Normalize a tool path to a repo-relative posix key (no leading ./)."""
    text = path.strip().replace("\\", "/")
    if not text:
        return ""
    if working_dir is not None:
        root = working_dir.resolve()
        candidate = (root / text).resolve()
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            return ""
    pure = PurePosixPath(text)
    parts = [p for p in pure.parts if p not in ("", ".")]
    return PurePosixPath(*parts).as_posix() if parts else ""


def _artifact_satisfies(path: Path, claim: dict[str, object]) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    if not isinstance(data, dict):
        return False
    return all(data.get(key) == expected for key, expected in claim.items())


def _shadow_checkpoint_base(working_dir: Path) -> Path:
    """Prefer Dream home checkpoints dir."""
    from dream.config.paths import DreamPaths

    return DreamPaths.resolve(working_dir).home / "checkpoints"


def _audience_for(value: object) -> ContextAudience | None:
    if value == ContextAudience.PLANNER.value:
        return ContextAudience.PLANNER
    if value == ContextAudience.EVALUATOR.value:
        return ContextAudience.EVALUATOR
    if value == ContextAudience.GENERATOR.value:
        return ContextAudience.GENERATOR
    return None
