"""Lattice consolidation tools — context, packet, apply (spec 07 / integration-plan §6).

Boundary: chorus parses agent JSON into lattice domain types and formats tool
observations. Lattice owns semantic validate/apply/forget.

Procedural memory is NOT written here — use ``skill_manage`` (Chorus SkillStore).
``habits[]`` on lattice_apply is rejected with a harness recovery contract.
"""

from __future__ import annotations

import json
from typing import Any

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from lattice.domain.proposal import PatternDraft, Proposal
from lattice.facade import Lattice
from pydantic import BaseModel, Field, ValidationError

from chorus.heartbeat import BeatContext

_LATTICE_TOOLS = frozenset({"lattice_context", "lattice_packet", "lattice_apply"})


class LatticeContextInput(BaseModel):
    query: str = Field(description="Search distilled patterns for this intent.")
    limit: int = Field(default=5, ge=1, le=20)


class LatticePacketInput(BaseModel):
    pass


class LatticeApplyInput(BaseModel):
    proposal: dict[str, Any] = Field(
        description=(
            "Proposal JSON with patterns[] (facts only). "
            "Procedural playbooks use skill_manage — not habits[] here."
        )
    )


class LatticeContextTool(BaseTool):
    name = "lattice_context"
    description = (
        "Distilled semantic patterns for this employee. Each hit lists src: run_ids — "
        "use get_run(run_id) for full beat prose on src: run_ids. "
        "For how-to playbooks use the skill tool / skill_manage(view), not this tool."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=10.0)
    input_model = LatticeContextInput

    def __init__(self, lattice: Lattice) -> None:
        self._lattice = lattice

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = LatticeContextInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(
                content=(
                    f"refused: malformed lattice_context input — {exc}. "
                    "Retry with query=str and optional limit=1..20."
                ),
                is_error=True,
                structured={"status": "error", "summary": "malformed input"},
            )
        beat = BeatContext.read(ctx.working_dir)
        content = self._lattice.context(beat.employee_id, args.query, k=args.limit)
        if not content.strip():
            return ToolResult(
                content="no distilled patterns matched. Try a broader query or recall().",
                structured={
                    "status": "empty",
                    "summary": "no patterns matched",
                    "next_actions": ["recall(query=…)", "widen lattice_context query"],
                },
            )
        return ToolResult(
            content=content,
            structured={"status": "success", "summary": "patterns returned"},
        )


class LatticePacketTool(BaseTool):
    name = "lattice_packet"
    description = (
        "Consolidation evidence bundle when the lattice gate is open. "
        "Returns engrams + cluster hints (pattern and/or habit evolve); empty when gate is closed."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=10.0)
    input_model = LatticePacketInput

    def __init__(self, lattice: Lattice) -> None:
        self._lattice = lattice

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        beat = BeatContext.read(ctx.working_dir)
        packet = self._lattice.packet(beat.employee_id)
        if packet is None:
            return ToolResult(
                content="gate closed — no consolidation packet. Do not consolidate this beat.",
                structured={
                    "status": "gate_closed",
                    "summary": "gate closed",
                    "next_actions": ["skip consolidation", "continue the task"],
                },
            )
        payload = {
            "employee_id": packet.employee_id,
            "engrams": [
                {
                    "run_id": ep.run_id,
                    "intent": ep.intent,
                    "outcome": ep.outcome,
                    "files_touched": list(ep.files_touched),
                }
                for ep in packet.engrams
            ],
            "hints": [
                {
                    "kind": h.kind.value,
                    "key_template": h.key_template,
                    "run_ids": list(h.run_ids),
                    "suggested_action": h.suggested_action.value if h.suggested_action else None,
                    "suggested_skill": h.suggested_skill,
                }
                for h in packet.hints
            ],
        }
        return ToolResult(
            content=json.dumps(payload, indent=2),
            structured={
                "status": "success",
                "summary": f"{len(packet.engrams)} engrams, {len(packet.hints)} hints",
                "packet": payload,
                "next_actions": [
                    "recall + get_run for cited run_ids",
                    "lattice_apply({patterns:[…]}) for facts",
                    "skill_manage(evolve|patch) for procedures",
                ],
            },
        )


class LatticeApplyTool(BaseTool):
    name = "lattice_apply"
    description = (
        "Apply a Proposal JSON with patterns[] (semantic facts only). "
        "Validate runs inside; gate should be open. "
        "For procedures use skill_manage(evolve|patch|create) — habits[] are rejected here. "
        "On success, runs the sleep forget pass (discount + weak-hint invalidation)."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=15.0)
    input_model = LatticeApplyInput

    def __init__(self, lattice: Lattice) -> None:
        self._lattice = lattice

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = LatticeApplyInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(
                content=(
                    f"refused: malformed lattice_apply input — {exc}. "
                    "Retry with proposal={patterns:[]}."
                ),
                is_error=True,
                structured={
                    "status": "error",
                    "summary": "malformed input",
                    "next_actions": ["lattice_apply({patterns:[…]})"],
                },
            )
        beat = BeatContext.read(ctx.working_dir)
        try:
            proposal = _parse_proposal(args.proposal, employee_id=beat.employee_id)
        except ValueError as exc:
            msg = str(exc)
            next_actions = ["fix patterns[] and cite done run_ids"]
            if "habits" in msg.lower() or "skill_manage" in msg.lower():
                next_actions = [
                    "skill_manage(action='evolve'|'patch'|'create')",
                    "lattice_apply({patterns:[…]}) for facts only",
                ]
            return ToolResult(
                content=f"refused: {msg}",
                is_error=True,
                structured={
                    "status": "error",
                    "summary": msg,
                    "root_cause": "proposal rejected at chorus boundary",
                    "retry": next_actions[0],
                    "stop": "do not dual-write habits via lattice_apply",
                    "next_actions": next_actions,
                },
            )
        result = self._lattice.apply(proposal)
        if not result.ok:
            errors = "; ".join(result.errors)
            return ToolResult(
                content=(
                    f"apply failed: {errors}. "
                    "Put sticky-note facts in patterns[]; "
                    "procedures → skill_manage; stop if the gate is closed."
                ),
                is_error=True,
                structured={
                    "status": "error",
                    "summary": "apply failed",
                    "errors": list(result.errors),
                    "next_actions": [
                        "fix validation errors",
                        "skill_manage for procedures",
                        "or skip consolidation",
                    ],
                },
            )
        forget_result = self._lattice.forget(beat.employee_id)
        summary = (
            f"ok — atoms_written={result.atoms_written}; "
            f"forget discounted={forget_result.atoms_discounted} "
            f"invalidated={forget_result.atoms_invalidated}"
        )
        return ToolResult(
            content=summary,
            structured={
                "status": "success",
                "summary": summary,
                "atoms_written": result.atoms_written,
                "forget_discounted": forget_result.atoms_discounted,
                "forget_invalidated": forget_result.atoms_invalidated,
                "next_actions": [
                    "skill_manage for procedural updates",
                    "use lattice_context for facts only",
                ],
            },
        )


def _parse_proposal(raw: dict[str, Any], *, employee_id: str) -> Proposal:
    """Bind employee_id from beat context — never trust model-supplied identity.

    habits[] are rejected here (sole procedural writer = skill_manage).
    """
    model_employee = raw.get("employee_id")
    if model_employee is not None and str(model_employee) != employee_id:
        raise ValueError(
            f"cross-employee proposal rejected (beat={employee_id!r}, proposal={model_employee!r})"
        )

    habits_raw = raw.get("habits")
    if habits_raw:
        raise ValueError(
            "habits[] are not accepted on lattice_apply; "
            "use skill_manage(action='evolve'|'patch'|'create') for procedural memory"
        )

    patterns_raw = raw.get("patterns")
    if patterns_raw is None:
        patterns_raw = []
    if not isinstance(patterns_raw, list):
        raise ValueError("patterns must be a list when present")
    if not patterns_raw:
        raise ValueError("proposal must contain a non-empty patterns list")

    patterns: list[PatternDraft] = []
    for item in patterns_raw:
        if not isinstance(item, dict):
            raise ValueError("each pattern must be an object")
        source_ids = item.get("source_run_ids") or ()
        if not isinstance(source_ids, list):
            raise ValueError("source_run_ids must be a list")
        patterns.append(
            PatternDraft(
                key=str(item["key"]),
                claim=str(item["claim"]),
                source_run_ids=tuple(str(s) for s in source_ids),
                supersedes=str(item["supersedes"]) if item.get("supersedes") else None,
            )
        )

    return Proposal(employee_id=employee_id, patterns=tuple(patterns), habits=())


def lattice_tool(name: str, lattice: Lattice) -> BaseTool | None:
    if name == "lattice_context":
        return LatticeContextTool(lattice)
    if name == "lattice_packet":
        return LatticePacketTool(lattice)
    if name == "lattice_apply":
        return LatticeApplyTool(lattice)
    return None


__all__ = [
    "_LATTICE_TOOLS",
    "LatticeApplyInput",
    "LatticeApplyTool",
    "LatticeContextInput",
    "LatticeContextTool",
    "LatticePacketInput",
    "LatticePacketTool",
    "lattice_tool",
]
