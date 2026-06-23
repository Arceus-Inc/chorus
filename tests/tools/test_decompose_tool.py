"""DecomposeTool — the chorus ``decompose`` capability as a model-callable dream tool (M3 Slice 1).

The tool is the dream envelope around :class:`~chorus.lifecycle.CapabilityService`: it validates the
model's children DAG, reads the per-beat :class:`~chorus.heartbeat.BeatContext` from ``ctx.working_dir``
to learn its parent task + run, and fans the task out. These tests drive ``execute`` directly (no model
in the loop) with a written beat-context file standing in for the kernel.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.heartbeat import BeatContext
from chorus.ledger import Run, RunStatus, SqliteLedger, Task, TaskStatus
from chorus.workforce import Employee
from chorus_tools import DecomposeTool

pytestmark = pytest.mark.integration

REV = "run_mgr_1"

# A real (de-placeholdered) contract: the contract-first gate (spec 15 §4.1) refuses to fan out until
# the manager has authored one, so every success case writes this into the beat's working dir.
_AUTHORED_AGENTS_MD = (
    "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — entry\n- `pkg/core.py` — Thing\n"
    "## Public API\n- `pkg.Thing`\n## Ownership\n- `pkg/core.py` -> ada\n"
)


def _author_contract(working_dir: Path) -> None:
    (working_dir / "AGENTS.md").write_text(_AUTHORED_AGENTS_MD, encoding="utf-8")


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _seed(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Mgr", role="manager"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))
    ledger.tasks.submit(Task(id="M", intent="ship it", status=TaskStatus.TODO, assignee_employee_id="mgr"))
    ledger.runs.create(Run(id=REV, employee_id="mgr", task_id="M", status=RunStatus.RUNNING))


def test_tool_fans_out_and_assigns(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    _author_contract(tmp_path)
    tool = DecomposeTool(ledger)

    result = asyncio.run(
        tool.execute(
            {
                "children": [
                    {"label": "api", "intent": "build the api", "assignee": "ada"},
                    {"label": "tests", "intent": "write tests", "assignee": "bob", "depends_on": ["api"]},
                ]
            },
            _ctx(tmp_path),
        )
    )

    assert result.is_error is False
    child_ids = result.structured["children"]
    assert set(child_ids) == {"api", "tests"}
    # children are real, assigned, and the parent waits on its subtree
    assert ledger.tasks.get(child_ids["api"]).assignee_employee_id == "ada"  # type: ignore[union-attr]
    assert set(ledger.dependencies.unresolved_blockers("M")) == set(child_ids.values())
    # the sibling edge is wired
    assert ledger.dependencies.unresolved_blockers(child_ids["tests"]) == [child_ids["api"]]


def test_tool_declares_a_repo_write_trust_tier(ledger: SqliteLedger) -> None:
    # A mutating tool is gated as a write effect; its declared tier must be REPO_WRITE (1) so dream
    # trusts it at the manager's session tier instead of denying it ("not trusted for write").
    assert DecomposeTool(ledger).declaration.tier_required == 1


def test_tool_rejects_empty_children(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    result = asyncio.run(DecomposeTool(ledger).execute({"children": []}, _ctx(tmp_path)))
    assert result.is_error is True


def test_tool_rejects_unknown_dependency_label(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    result = asyncio.run(
        DecomposeTool(ledger).execute(
            {"children": [{"label": "api", "intent": "x", "assignee": "ada", "depends_on": ["ghost"]}]},
            _ctx(tmp_path),
        )
    )
    assert result.is_error is True
    assert ledger.tasks.get("M") is not None  # nothing fanned out


def test_tool_is_idempotent_on_refire(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    _author_contract(tmp_path)
    tool = DecomposeTool(ledger)
    payload = {"children": [{"label": "api", "intent": "build the api", "assignee": "ada"}]}
    first = asyncio.run(tool.execute(payload, _ctx(tmp_path)))
    second = asyncio.run(tool.execute(payload, _ctx(tmp_path)))  # the generator re-fired
    assert first.structured["children"] == second.structured["children"]
    assert len(ledger.dependencies.unresolved_blockers("M")) == 1  # no duplicate child


def test_tool_refuses_to_fan_out_with_no_contract(ledger: SqliteLedger, tmp_path: Path) -> None:
    # spec 15 §4.1: the manager must author AGENTS.md BEFORE decomposing — else engineers branch off a
    # blank form. No AGENTS.md in the working dir → the fan-out is refused and nothing is created.
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    result = asyncio.run(
        DecomposeTool(ledger).execute(
            {"children": [{"label": "api", "intent": "x", "assignee": "ada"}]}, _ctx(tmp_path)
        )
    )
    assert result.is_error is True
    assert result.structured["contract_unauthored"] is True
    assert ledger.tasks.children("M") == []  # nothing fanned out


def test_tool_refuses_to_fan_out_with_placeholder_contract(ledger: SqliteLedger, tmp_path: Path) -> None:
    # the seeded skeleton (still carrying <package>/<Symbol> markers) counts as unauthored — refuse.
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `<package>/__init__.py` — entry\n"
        "## Public API\n- `<package>.<Symbol>`\n## Ownership\n- `<package>/<file>.py` -> <id>\n",
        encoding="utf-8",
    )
    result = asyncio.run(
        DecomposeTool(ledger).execute(
            {"children": [{"label": "api", "intent": "x", "assignee": "ada"}]}, _ctx(tmp_path)
        )
    )
    assert result.is_error is True
    assert result.structured["contract_unauthored"] is True
    assert ledger.tasks.children("M") == []


def test_tool_derives_one_task_per_module_from_the_contract(ledger: SqliteLedger, tmp_path: Path) -> None:
    # spec 15 B: with NO children, the kernel fans out one task per declared module — owner + depends_on
    # from AGENTS.md — so the hard module lands in its own focused task, never bundled.
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — entry\n- `pkg/ingest.py` — load\n"
        "- `pkg/model.py` — the algorithm\n## Public API\n- `pkg.fit`\n"
        "## Ownership\n- `pkg/__init__.py` -> ada\n- `pkg/ingest.py` -> ada\n- `pkg/model.py` -> bob\n"
        "## Dependencies\n- `pkg/model.py` -> `pkg/ingest.py`\n",
        encoding="utf-8",
    )
    result = asyncio.run(DecomposeTool(ledger).execute({}, _ctx(tmp_path)))  # NO children → derive

    assert result.is_error is False
    child_ids = result.structured["children"]
    assert set(child_ids) == {"pkg-__init__-py", "pkg-ingest-py", "pkg-model-py"}
    # the hard module is its OWN task, assigned to its declared owner
    assert ledger.tasks.get(child_ids["pkg-model-py"]).assignee_employee_id == "bob"  # type: ignore[union-attr]
    # model depends on ingest (declared); ingest is a foundation (no deps)
    assert ledger.dependencies.unresolved_blockers(child_ids["pkg-model-py"]) == [child_ids["pkg-ingest-py"]]


def test_tool_refuses_contract_derive_when_a_module_is_owned_by_a_non_engineer(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    # spec 15 B: a deliverable module must be owned by an ENGINEER. A PM/analyst/reviewer coordinates;
    # it has no build->review->land path, so a module assigned to it SUCCEEDS its beat yet never lands
    # and the dependent __init__ cascade-cancels (the prefrank `cli.py -> pat` block). Fail closed so the
    # manager reassigns the module to an engineer report.
    _seed(ledger)
    ledger.employees.create(Employee(id="pat", name="Pat", role="pm", reports_to="mgr"))
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — entry\n- `pkg/model.py` — algo\n"
        "## Public API\n- `pkg.fit`\n## Ownership\n- `pkg/__init__.py` -> ada\n- `pkg/model.py` -> pat\n",
        encoding="utf-8",
    )
    result = asyncio.run(DecomposeTool(ledger).execute({}, _ctx(tmp_path)))
    assert result.is_error is True
    assert "pkg-model-py" in result.structured["non_engineer_owners"]
    assert ledger.tasks.children("M") == []  # nothing fanned out


def test_tool_refuses_contract_derive_when_a_module_has_no_owner(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — entry\n- `pkg/model.py` — algo\n"
        "## Public API\n- `pkg.fit`\n## Ownership\n- `pkg/__init__.py` -> ada\n",  # model.py unowned
        encoding="utf-8",
    )
    result = asyncio.run(DecomposeTool(ledger).execute({}, _ctx(tmp_path)))
    assert result.is_error is True
    assert result.structured["unowned_modules"] == ["pkg/model.py"]
    assert ledger.tasks.children("M") == []
