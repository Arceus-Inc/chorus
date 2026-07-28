"""Dream lifecycle hooks Chorus registers at materialize (S1 #2 / #11 L1).

Hermes-aligned:
- PRE_TOOL_USE allow_block — dangerous command veto
- STOP allow_continue — evidence missing → nudge parent to spawn critic
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dream.contracts.hook import HookEvent, HookResult, HookSpec

from chorus.roles._subagent import SubagentSpec

__all__ = [
    "DangerousToolVetoHook",
    "EvidenceContinueHook",
    "register_employee_hooks",
]

_DANGEROUS_BASH = re.compile(
    r"(?:rm\s+-rf\s+/|mkfs\.|dd\s+if=.*of=/dev/|"
    r"curl\s+[^\n]*\|\s*(?:ba)?sh|wget\s+[^\n]*\|\s*(?:ba)?sh)",
    re.IGNORECASE,
)


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


class EvidenceContinueHook:
    """STOP continue when required subagent evidence artifacts are missing (#11 L1)."""

    def __init__(
        self,
        requirements: tuple[tuple[str, str, dict[str, object]], ...],
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
        if payload.get("role") != "generator":
            return HookResult()
        if payload.get("phase") not in (None, "pre_seal"):
            return HookResult()
        missing: list[str] = []
        for name, relative, claim in self._requirements:
            path = self._working_dir / relative
            if not _artifact_satisfies(path, claim):
                missing.append(name)
        if not missing:
            return HookResult()
        return HookResult(
            continue_message=(
                "Evidence incomplete for: "
                + ", ".join(missing)
                + ". Spawn the required critic/verifier (or write a valid verdict file) "
                "before finishing this beat."
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
    evidence = tuple(
        (spec.name, spec.evidence_path, dict(spec.evidence_claim))
        for spec in subagents
        if spec.evidence_path is not None and spec.evidence_claim is not None
    )
    if evidence:
        register(EvidenceContinueHook(evidence, working_dir=working_dir))


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
