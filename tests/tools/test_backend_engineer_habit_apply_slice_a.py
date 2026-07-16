"""backend_engineer skill_manage EVOLVE + versioned materialize (Chorus SkillStore)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus.memory import EpisodicStore, SprintDelta
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod
from chorus_harness._skills import materialize_versioned_skills_into

pytestmark = pytest.mark.integration

_EVOLVE_BODY = (
    "## Before patching HTTP clients\n\n"
    "1. Call `get_run(run_id)` for each cited beat and recall the failure shape.\n"
    "2. Classify transient (429/503) versus logic error before editing.\n"
    "3. Only then edit `src/api/client.py`.\n\n"
    "## Pitfalls\n"
    "- Patching without reading prior beat prose repeats the same mistake.\n\n"
    "## Verification\n"
    "- `test_evidence` passes after the patch.\n"
)


def _delta(run_id: str, *, employee_id: str = "bex") -> SprintDelta:
    now = datetime.now(UTC)
    return SprintDelta(
        run_id=run_id,
        task_id="t1",
        employee_id=employee_id,
        role="backend_engineer",
        scope="project",
        intent="retry",
        outcome="done",
        score=1.0,
        created_at=now,
        recorded_at=now,
        artifacts=(),
        files_touched=("src/api/client.py",),
        body="beat",
    )


def _ctx(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=working_dir, session_id="sess")


def _factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
    )
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
    )
    return factory, captured


def test_backend_engineer_habit_evolve_via_skill_manage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    store = EpisodicStore(factory.company_root / "memory")
    store.append(_delta("r0"))
    store.append(_delta("r1"))

    mat = factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    canonical = mat.working_dir / ".harness" / "skills" / "structuring-any-service" / "SKILL.md"
    assert canonical.is_file()

    tool = next(t for t in captured["registry"].list_tools() if t.name == "skill_manage")
    BeatContext(employee_id="bex", run_id="run_a", task_id="t6-lattice-consolidate").write(
        mat.working_dir
    )

    result = asyncio.run(
        tool.execute(
            {
                "action": "evolve",
                "name": "structuring-any-service",
                "section": "Before patching HTTP clients",
                "content": _EVOLVE_BODY,
                "source_run_ids": ["r0", "r1"],
            },
            _ctx(mat.working_dir),
        )
    )
    assert result.is_error is False, result.content
    assert result.structured.get("status") == "success"
    assert result.structured.get("artifacts", {}).get("revision_no") == 1

    skills_dir = mat.working_dir / ".harness" / "skills"
    materialize_versioned_skills_into(
        skills_dir,
        company_root=factory.company_root,
        employee_id="bex",
    )
    merged = skills_dir / "structuring-any-service" / "SKILL.md"
    text = merged.read_text(encoding="utf-8")
    assert "Before patching HTTP clients" in text
    assert "when_to_use" in text


def test_lattice_apply_rejects_habits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    store = EpisodicStore(factory.company_root / "memory")
    store.append(_delta("r0"))

    mat = factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    tool = next(t for t in captured["registry"].list_tools() if t.name == "lattice_apply")
    BeatContext(employee_id="bex", run_id="run_a", task_id="t6").write(mat.working_dir)

    result = asyncio.run(
        tool.execute(
            {
                "proposal": {
                    "habits": [
                        {
                            "action": "evolve",
                            "skill": "structuring-any-service",
                            "section": "X",
                            "body": _EVOLVE_BODY,
                            "source_run_ids": ["r0"],
                        }
                    ]
                }
            },
            _ctx(mat.working_dir),
        )
    )
    assert result.is_error is True
    assert result.structured.get("status") == "error"
    assert "skill_manage" in result.content
    assert any("skill_manage" in a for a in result.structured.get("next_actions", []))


def test_materialize_versioned_skills_into_worktree(tmp_path: Path) -> None:
    from chorus.skills import SkillManager, SkillStore

    company = tmp_path / "acme"
    canonical_root = tmp_path / "canonical"
    skill = canonical_root / "structuring-any-service"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: structuring-any-service\n"
        "description: canonical\n"
        "when_to_use: before writing a service\n"
        "---\n\n# Structuring\n\nCanonical body.\n",
        encoding="utf-8",
    )

    store = SkillStore(company / "skills")
    mgr = SkillManager(
        store,
        employee_id="bex",
        canonical_skills_root=canonical_root,
        episodes=(_Ep("r0"),),
    )
    try:
        obs = mgr.apply(
            action="evolve",
            name="structuring-any-service",
            section="Before patching HTTP clients",
            content=_EVOLVE_BODY,
            source_run_ids=["r0"],
        )
        assert obs.status == "success", obs.summary
    finally:
        mgr.close()

    skills_dir = tmp_path / "worktree" / ".harness" / "skills"
    skills_dir.mkdir(parents=True)
    canonical = skills_dir / "structuring-any-service"
    canonical.mkdir()
    (canonical / "SKILL.md").write_text(
        (skill / "SKILL.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    materialize_versioned_skills_into(
        skills_dir,
        company_root=company,
        employee_id="bex",
    )
    merged = skills_dir / "structuring-any-service" / "SKILL.md"
    text = merged.read_text(encoding="utf-8")
    assert "when_to_use: before writing a service" in text
    assert "Canonical body." in text
    assert "Before patching HTTP clients" in text
    assert not merged.stat().st_mode & 0o200


class _Ep:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.employee_id = "bex"
        self.outcome = "done"
