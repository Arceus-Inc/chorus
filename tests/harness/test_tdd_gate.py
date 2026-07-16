from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel

from chorus_harness._tdd_gate import TddProductionGate


class _Input(BaseModel):
    path: str = "backend/service.py"


class _Tool(BaseTool):
    name = "write_file"
    description = "test tool"
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=10)
    input_model = _Input

    def __init__(self, action: Any | None = None) -> None:
        self.calls = 0
        self._action = action

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        self.calls += 1
        if self._action is not None:
            self._action(input, ctx)
        return ToolResult(content='{"authored": true}', metadata={})


def _ctx(
    root: Path, *, role: str = "generator", subagent: str | None = None
) -> ToolExecutionContext:
    metadata: dict[str, object] = {"dream.role": role}
    if subagent is not None:
        metadata["dream.subagent_name"] = subagent
    return ToolExecutionContext(working_dir=root, session_id="session", metadata=metadata)


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='0'\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)


def _write_red(root: Path, *, dirty_production: bool = False) -> None:
    test_path = root / "tests" / "test_service.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_missing():\n    assert False\n", encoding="utf-8")
    (root / "test_plan.json").write_text('{"authored": true}\n', encoding="utf-8")
    bundle = root / "test_evidence"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "red.json").write_text(
        json.dumps(
            {
                "verdict": "red-confirmed",
                "test_paths": ["tests/test_service.py"],
                "test_hashes": {
                    "tests/test_service.py": hashlib.sha256(test_path.read_bytes()).hexdigest()
                },
                "production_paths": [],
            }
        ),
        encoding="utf-8",
    )
    if dirty_production:
        production = root / "backend" / "service.py"
        production.parent.mkdir(parents=True, exist_ok=True)
        production.write_text("implemented = True\n", encoding="utf-8")


async def test_parent_production_write_is_denied_before_test_author(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    delegate = _Tool()
    gated = TddProductionGate(tmp_path).wrap(delegate)

    result = await gated.execute({"path": "backend/service.py"}, _ctx(tmp_path))

    assert result.is_error is True
    assert result.metadata["root_cause"] == "strict_tdd_red_not_authorized"
    assert delegate.calls == 0


async def test_clean_test_author_completion_unlocks_parent_production(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    def author(_input: dict[str, Any], ctx: ToolExecutionContext) -> None:
        _write_red(ctx.working_dir)

    gate = TddProductionGate(tmp_path)
    spawn = _Tool(author)
    spawn.name = "spawn_subagent"
    await gate.wrap(spawn).execute({"name": "test_author"}, _ctx(tmp_path))
    production = _Tool()

    result = await gate.wrap(production).execute({"path": "backend/service.py"}, _ctx(tmp_path))

    assert result.is_error is False
    assert production.calls == 1


async def test_typed_test_author_result_canonicalizes_plan_before_unlock(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)

    def author(_input: dict[str, Any], ctx: ToolExecutionContext) -> None:
        _write_red(ctx.working_dir)
        (ctx.working_dir / "test_plan.json").write_text(
            '{"scope": "behavior contract"}\n', encoding="utf-8"
        )

    gate = TddProductionGate(tmp_path)
    spawn = _Tool(author)
    spawn.name = "spawn_subagent"
    await gate.wrap(spawn).execute({"name": "test_author"}, _ctx(tmp_path))
    production = _Tool()

    result = await gate.wrap(production).execute({"path": "backend/service.py"}, _ctx(tmp_path))

    assert result.is_error is False
    assert json.loads((tmp_path / "test_plan.json").read_text(encoding="utf-8")) == {
        "authored": True
    }


async def test_test_author_cannot_unlock_after_production_mutation(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    def author(_input: dict[str, Any], ctx: ToolExecutionContext) -> None:
        _write_red(ctx.working_dir, dirty_production=True)

    gate = TddProductionGate(tmp_path)
    spawn = _Tool(author)
    spawn.name = "spawn_subagent"
    await gate.wrap(spawn).execute({"name": "test_author"}, _ctx(tmp_path))
    production = _Tool()

    result = await gate.wrap(production).execute({"path": "backend/service.py"}, _ctx(tmp_path))

    assert result.is_error is True
    assert production.calls == 0


async def test_test_author_itself_retains_test_writing_tools(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    delegate = _Tool()
    gated = TddProductionGate(tmp_path).wrap(delegate)

    result = await gated.execute(
        {"path": "tests/test_service.py"},
        _ctx(tmp_path, role="subagent", subagent="test_author"),
    )

    assert result.is_error is False
    assert delegate.calls == 1


async def test_machine_certified_red_is_reused_for_correction_beat(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_red(tmp_path)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "valid prior beat"], cwd=tmp_path, check=True)
    artifact = tmp_path / "test_plan.json"
    provenance = tmp_path / ".harness" / "subagent-evidence" / "test_author.json"
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(
        json.dumps(
            {
                "artifact_path": "test_plan.json",
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "required_claim": {"authored": True},
                "evidence_read_only": False,
            }
        ),
        encoding="utf-8",
    )
    production = _Tool()

    result = (
        await TddProductionGate(tmp_path)
        .wrap(production)
        .execute({"path": "backend/service.py"}, _ctx(tmp_path))
    )

    assert result.is_error is False
    assert production.calls == 1
