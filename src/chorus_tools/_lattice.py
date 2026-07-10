"""Lattice consolidation tools — context, packet, apply (spec 07 / integration-plan §6)."""

from __future__ import annotations

import json
from typing import Any

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.heartbeat import BeatContext
from lattice.domain.proposal import PatternDraft, Proposal
from lattice.facade import Lattice

_LATTICE_TOOLS = frozenset({"lattice_context", "lattice_packet", "lattice_apply"})


class LatticeContextInput(BaseModel):
    query: str = Field(description="Search distilled patterns for this intent.")
    limit: int = Field(default=5, ge=1, le=20)


class LatticePacketInput(BaseModel):
    pass


class LatticeApplyInput(BaseModel):
    proposal: dict[str, Any] = Field(description="Patterns-only Proposal JSON.")


class LatticeContextTool(BaseTool):
    name = "lattice_context"
    description = (
        "Distilled semantic patterns for this employee. Each hit lists src: run_ids — "
        "use get_run(run_id) for full beat prose on src: run_ids."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=10.0)
    input_model = LatticeContextInput

    def __init__(self, lattice: Lattice) -> None:
        self._lattice = lattice

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = LatticeContextInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(content=f"refused: malformed lattice_context input — {exc}", is_error=True)
        beat = BeatContext.read(ctx.working_dir)
        content = self._lattice.context(beat.employee_id, args.query, k=args.limit)
        if not content.strip():
            return ToolResult(content="no distilled patterns matched.", structured={"status": "empty"})
        return ToolResult(content=content, structured={"status": "success"})


class LatticePacketTool(BaseTool):
    name = "lattice_packet"
    description = (
        "Consolidation evidence bundle when the lattice gate is open. "
        "Returns engrams + cluster hints; empty when gate is closed."
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
                content="gate closed — no consolidation packet.",
                structured={"status": "gate_closed"},
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
                {"key_template": h.key_template, "run_ids": list(h.run_ids)}
                for h in packet.hints
            ],
        }
        return ToolResult(
            content=json.dumps(payload, indent=2),
            structured={"status": "success", "packet": payload},
        )


class LatticeApplyTool(BaseTool):
    name = "lattice_apply"
    description = (
        "Apply a patterns-only Proposal JSON. Validate runs inside; gate should be open. "
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
            return ToolResult(content=f"refused: malformed lattice_apply input — {exc}", is_error=True)
        beat = BeatContext.read(ctx.working_dir)
        try:
            proposal = _parse_proposal(args.proposal, employee_id=beat.employee_id)
        except ValueError as exc:
            return ToolResult(content=f"refused: {exc}", is_error=True)
        result = self._lattice.apply(proposal)
        if not result.ok:
            errors = "; ".join(result.errors)
            return ToolResult(content=f"apply failed: {errors}", is_error=True)
        forget_result = self._lattice.forget(beat.employee_id)
        return ToolResult(
            content=(
                f"ok — patterns_written={result.patterns_written}; "
                f"forget discounted={forget_result.atoms_discounted} "
                f"invalidated={forget_result.atoms_invalidated}"
            ),
            structured={
                "status": "success",
                "patterns_written": result.patterns_written,
                "forget_discounted": forget_result.atoms_discounted,
                "forget_invalidated": forget_result.atoms_invalidated,
            },
        )


def _parse_proposal(raw: dict[str, Any], *, employee_id: str) -> Proposal:
    """Bind employee_id from beat context — never trust model-supplied identity."""
    model_employee = raw.get("employee_id")
    if model_employee is not None and str(model_employee) != employee_id:
        raise ValueError(
            f"cross-employee proposal rejected (beat={employee_id!r}, proposal={model_employee!r})"
        )
    patterns_raw = raw.get("patterns")
    if not isinstance(patterns_raw, list) or not patterns_raw:
        raise ValueError("proposal must contain a non-empty patterns list")
    patterns: list[PatternDraft] = []
    for item in patterns_raw:
        if not isinstance(item, dict):
            raise ValueError("each pattern must be an object")
        source_ids = item.get("source_run_ids") or ()
        if isinstance(source_ids, list):
            source_tuple = tuple(str(s) for s in source_ids)
        else:
            raise ValueError("source_run_ids must be a list")
        patterns.append(
            PatternDraft(
                key=str(item["key"]),
                claim=str(item["claim"]),
                source_run_ids=source_tuple,
                supersedes=str(item["supersedes"]) if item.get("supersedes") else None,
            )
        )
    return Proposal(employee_id=employee_id, patterns=tuple(patterns))


def lattice_tool(name: str, lattice: Lattice) -> BaseTool | None:
    if name == "lattice_context":
        return LatticeContextTool(lattice)
    if name == "lattice_packet":
        return LatticePacketTool(lattice)
    if name == "lattice_apply":
        return LatticeApplyTool(lattice)
    return None


__all__ = [
    "LatticeApplyInput",
    "LatticeApplyTool",
    "LatticeContextInput",
    "LatticeContextTool",
    "LatticePacketInput",
    "LatticePacketTool",
    "_LATTICE_TOOLS",
    "lattice_tool",
]
