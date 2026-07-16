"""Machine-enforced RED authorization for strict-TDD employee harnesses."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration, ToolEffects
from dream.tools._context import ToolExecutionContext
from dream.tools._registry import ToolRegistry
from pydantic import BaseModel

_PRODUCTION_CAPABLE_TOOLS = frozenset({"bash", "git", "write_file"})
_RED_ALLOWED_PREFIXES = (".dream/", ".harness/", "docs/exec-plans/", "test_evidence/")
_RED_ALLOWED_PATHS = frozenset({"TODO.md", "test_plan.json"})
_SUBAGENT_NAME_KEY = "dream.subagent_name"


class _PlaceholderInput(BaseModel):
    pass


class _TddGatedTool(BaseTool):
    """Transparent proxy around one tool participating in the TDD gate."""

    name = "tdd_gated_tool"
    description = "Tool protected by strict TDD authorization."
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=1)
    input_model: type[BaseModel] = _PlaceholderInput

    def __init__(self, delegate: BaseTool, gate: TddProductionGate) -> None:
        self._delegate = delegate
        self._gate = gate
        self.name = delegate.name
        self.description = delegate.description
        self.declaration = delegate.declaration
        self.input_model = delegate.input_model

    def effects_for(self, input: dict[str, Any]) -> ToolEffects:
        return self._delegate.effects_for(input)

    def is_read_only_for(self, input: dict[str, Any]) -> bool:
        return self._delegate.is_read_only_for(input)

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        if self.name == "spawn_subagent":
            result = await self._delegate.execute(input, ctx)
            if input.get("name") == "test_author" and not result.is_error:
                self._gate.authorize_from_test_author(result.content)
            return result

        if (
            self.name in _PRODUCTION_CAPABLE_TOOLS
            and ctx.metadata.get(_SUBAGENT_NAME_KEY) != "test_author"
            and not self._gate.authorized
        ):
            return ToolResult(
                content=(
                    "Strict TDD gate denied production-capable tooling until the independent "
                    "test_author completes with valid RED-before-production evidence."
                ),
                is_error=True,
                metadata={
                    "root_cause": "strict_tdd_red_not_authorized",
                    "safe_retry": (
                        "spawn test_author with the exact assigned criteria; let it author the tests "
                        "and obtain a red-confirmed test_evidence/red.json"
                    ),
                    "stop_condition": "do not write or mutate production before RED authorization",
                },
            )
        return await self._delegate.execute(input, ctx)


class TddProductionGate:
    """Unlock production-capable tools only after independently authored, clean RED."""

    def __init__(self, worktree: Path) -> None:
        self._worktree = worktree.resolve()
        self.authorized = self._has_reusable_machine_provenance()

    def wrap(self, tool: BaseTool) -> BaseTool:
        if tool.name == "spawn_subagent" or tool.name in _PRODUCTION_CAPABLE_TOOLS:
            return _TddGatedTool(tool, self)
        return tool

    def wrap_registry(self, registry: ToolRegistry) -> ToolRegistry:
        wrapped = ToolRegistry()
        for tool, source in registry.iter_with_source():
            wrapped.register(self.wrap(tool), source=source)
        return wrapped

    def authorize_from_test_author(self, typed_output: str) -> None:
        try:
            returned = json.loads(typed_output)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(returned, dict) or returned.get("authored") is not True:
            return
        if not self._valid_red() or self._changed_production_paths():
            return
        artifact_path = self._worktree / "test_plan.json"
        temporary_path = artifact_path.with_suffix(".json.tmp")
        try:
            temporary_path.write_text(
                json.dumps(returned, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            temporary_path.replace(artifact_path)
        except OSError:
            temporary_path.unlink(missing_ok=True)
            return
        self.authorized = True

    def _has_reusable_machine_provenance(self) -> bool:
        provenance = self._read_object(".harness/subagent-evidence/test_author.json")
        artifact_path = self._worktree / "test_plan.json"
        if provenance is None or not artifact_path.is_file():
            return False
        if (
            provenance.get("artifact_path") != "test_plan.json"
            or provenance.get("required_claim") != {"authored": True}
            or provenance.get("evidence_read_only") is not False
            or provenance.get("artifact_sha256")
            != hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        ):
            return False
        plan = self._read_object("test_plan.json")
        return (
            plan is not None
            and plan.get("authored") is True
            and self._valid_red()
            and not self._changed_production_paths()
        )

    def _valid_red(self) -> bool:
        red = self._read_object("test_evidence/red.json")
        if red is None or red.get("verdict") != "red-confirmed":
            return False
        if red.get("production_paths") not in (None, []):
            return False
        test_paths = red.get("test_paths")
        test_hashes = red.get("test_hashes")
        if not isinstance(test_paths, list) or not test_paths or not isinstance(test_hashes, dict):
            return False
        for raw_path in test_paths:
            if not isinstance(raw_path, str):
                return False
            path = (self._worktree / raw_path).resolve()
            try:
                path.relative_to(self._worktree)
            except ValueError:
                return False
            if (
                not path.is_file()
                or test_hashes.get(raw_path) != hashlib.sha256(path.read_bytes()).hexdigest()
            ):
                return False
        return True

    def _changed_production_paths(self) -> tuple[str, ...]:
        red = self._read_object("test_evidence/red.json") or {}
        test_paths = {
            str(path).strip().replace("\\", "/").removeprefix("./")
            for path in red.get("test_paths", [])
            if isinstance(path, str)
        }
        changed: set[str] = set()
        for command in (
            ("git", "diff", "--name-only", "--no-renames", "HEAD"),
            ("git", "diff", "--cached", "--name-only", "--no-renames", "HEAD"),
            ("git", "ls-files", "--others", "--exclude-standard"),
        ):
            result = subprocess.run(
                command,
                cwd=self._worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return ("<git-inspection-failed>",)
            changed.update(
                path.strip().replace("\\", "/").removeprefix("./")
                for path in result.stdout.splitlines()
                if path.strip()
            )
        return tuple(
            sorted(
                path
                for path in changed
                if path not in test_paths
                and path not in _RED_ALLOWED_PATHS
                and not path.startswith(_RED_ALLOWED_PREFIXES)
            )
        )

    def _read_object(self, relative_path: str) -> dict[str, Any] | None:
        try:
            value = json.loads((self._worktree / relative_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        return value if isinstance(value, dict) else None


__all__ = ["TddProductionGate"]
