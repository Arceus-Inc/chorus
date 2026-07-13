"""skill_manage — sole procedural writer (Hermes-shaped; Chorus SkillStore SoT)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.heartbeat import BeatContext
from chorus.memory import EpisodicStore, SprintDelta
from chorus.skills import SkillManager, SkillStore


class SkillManageInput(BaseModel):
    action: Literal[
        "view", "create", "evolve", "patch", "edit", "restore", "delete", "list_versions"
    ] = Field(
        description=("Prefer patch/evolve over create. Facts → lattice_apply patterns[] only.")
    )
    name: str | None = Field(default=None, description="Skill slug")
    content: str | None = Field(default=None, description="Full SKILL.md or section body")
    section: str | None = Field(default=None, description="Heading for evolve")
    old_string: str | None = Field(default=None, description="patch find")
    new_string: str | None = Field(default=None, description="patch replace")
    source_run_ids: list[str] = Field(default_factory=list)
    label: str | None = None
    version_id: str | None = Field(default=None, description="restore target revision id")
    replace_all: bool = False


class SkillManageTool(BaseTool):
    name = "skill_manage"
    description = (
        "Procedural memory CRUD (Hermes skill_manage). "
        "Prefer evolve/patch of role umbrellas; CREATE only for class-level playbooks. "
        "Never save diary sticky notes. Facts go to lattice_apply patterns[] — not here."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=20.0)
    input_model = SkillManageInput

    def __init__(
        self,
        *,
        company_root: Path,
        canonical_skills_root: Path | None = None,
    ) -> None:
        self._company_root = Path(company_root)
        self._canonical_skills_root = (
            Path(canonical_skills_root) if canonical_skills_root is not None else None
        )

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = SkillManageInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(
                content=(
                    f"refused: malformed skill_manage input — {exc}. "
                    "Retry with action=view|evolve|patch|…"
                ),
                is_error=True,
                structured={
                    "status": "error",
                    "summary": "malformed input",
                    "root_cause": "ValidationError",
                    "retry": "fix fields against schema",
                    "stop": "do not invent parameters",
                    "next_actions": ["skill_manage(action='view')"],
                },
            )

        beat = BeatContext.read(ctx.working_dir)
        store = SkillStore(self._company_root / "skills")
        episodes: tuple[SprintDelta, ...] = ()
        try:
            episodic = EpisodicStore(self._company_root / "memory")
            try:
                episodes = tuple(episodic.records_for(beat.employee_id, limit=50))
            finally:
                episodic.close()
        except Exception:
            episodes = ()

        mgr = SkillManager(
            store,
            employee_id=beat.employee_id,
            canonical_skills_root=self._canonical_skills_root,
            episodes=episodes,
        )
        try:
            obs = mgr.apply(
                action=args.action,
                name=args.name,
                content=args.content,
                section=args.section,
                old_string=args.old_string,
                new_string=args.new_string,
                source_run_ids=args.source_run_ids,
                label=args.label,
                version_id=args.version_id,
                replace_all=args.replace_all,
            )
        finally:
            mgr.close()

        structured: dict[str, Any] = obs.as_dict()
        return ToolResult(
            content=obs.summary,
            is_error=obs.status == "error",
            structured=structured,
        )


__all__ = ["SkillManageInput", "SkillManageTool"]
