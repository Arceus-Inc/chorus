"""EmployeeHarnessFactory — the org's one role-faithful materializer (spec 06 §2 → dream seam).

dream's harness build is stubbed so the role → harness translation is tested without a provider; the
worktree side-effects run on real git in a temp dir.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from chorus.heartbeat import BeatRunner
from chorus.ledger import SqliteLedger
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration


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


def test_engineer_materializes_a_writable_harness_in_its_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="engineer"))
    # the engineer works confined to its own branch-isolated worktree under the org root
    assert mat.working_dir == tmp_path / "acme" / "worktrees" / "ada"
    assert mat.workspace is not None
    names = {t.name for t in captured["registry"].list_tools()}
    assert names == {
        "read_file",
        "write_file",
        "bash",
        "git",
        "todo_write",
        "skill",
        "memory_search",
        "memory_get",
        "recall",
        "get_run",
        "lattice_context",
        "lattice_packet",
        "lattice_apply",
    }
    assert mat.config.permission_mode == "acceptEdits"
    assert captured["max_turns"] == 12  # the engine scalars come from the role too
    assert captured["working_memory"] is True


def test_engineer_role_overlays_admit_read_memory_for_read_only_heads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The evaluator is the read-only head that keeps tools, so it admits the safe read-memory surfaces
    # (memory_search/memory_get/working_memory_read) to verify with. The planner is deliberately
    # TOOLLESS (`tools = []`) — given tools + tool_choice="auto", weaker models emit a tool call with
    # zero text and `run_task` fails with "planner reply missing <spec>" (see write_role_overlays). The
    # generator runs tools=null (no `tools =` line), so it sees the full role toolset.
    factory, _ = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="engineer"))

    planner = (mat.working_dir / ".harness" / "roles" / "planner.toml").read_text(encoding="utf-8")
    evaluator = (mat.working_dir / ".harness" / "roles" / "evaluator.toml").read_text(
        encoding="utf-8"
    )
    generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text(
        encoding="utf-8"
    )

    assert "tools = []" in planner  # toolless on purpose
    assert "PLANNER PHASE" in planner
    assert '"memory_search"' in evaluator
    assert '"memory_get"' in evaluator
    assert '"working_memory_read"' in evaluator
    assert "tools =" not in generator


def test_engineer_gets_an_unrestricted_sandbox_so_it_can_run_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # the engineer must run tests/builds (arbitrary commands), which dream gates behind an interactive
    # approval the autonomous kernel can't supply — so its trust posture is unrestricted-in-worktree.
    factory, _ = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="engineer"))
    sandbox = (mat.working_dir / ".harness" / "sandbox.toml").read_text(encoding="utf-8")
    assert 'tier = "unrestricted"' in sandbox
    assert "confirm_unrestricted = true" in sandbox  # dream double-gates it; the choice is explicit
    assert mat.config.sandbox == "unrestricted"


def test_pm_materializes_its_skill_bundle_into_the_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A role with skills (the PM) gets its bundle copied INTO the worktree, so the model can reach the
    # bundled reference files with its worktree-confined read_file — and dream's registry is pointed at
    # that in-worktree copy (skills enabled + a registry supplied).
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="pat", name="Pat", role="pm"))

    canvas = mat.working_dir / ".harness" / "skills" / "recommendation-canvas"
    assert (canvas / "SKILL.md").exists()
    # the bundled reference files the SKILL.md points at come across too — the whole reason for Option C
    assert (canvas / "template.md").exists()
    assert (canvas / "references" / "sample.md").exists()
    assert captured["skill_registry"] is not None
    assert captured["skills"] is True


def test_materialized_skill_bundle_is_git_excluded_from_the_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The whole point of homing the bundle under .harness/: it is already excluded from every worktree
    # branch (chorus.workspace info/exclude), so a skill's files never get committed or merged as a
    # deliverable. git must not see .harness/skills as an untracked path.
    factory, _ = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="pat", name="Pat", role="pm"))

    status = subprocess.run(
        ["git", "-C", str(mat.working_dir), "status", "--porcelain", "--ignored"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # excluded paths surface under `!!` (ignored), never as untracked `??`
    assert "?? .harness/skills" not in status
    assert not any(
        line.startswith("?? ") and ".harness/skills" in line for line in status.splitlines()
    )


def test_reviewer_materializes_a_read_only_harness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="rob", name="Rob", role="reviewer"))
    # the headline win: a reviewer is read-only EVERYWHERE — not just in chat. Its only tool with no
    # ledger is read_file (submit_verdict needs a ledger to bind to, registered in the ledger-bound test).
    names = {t.name for t in captured["registry"].list_tools()}
    assert names == {"read_file"}
    # DEFAULT permission so it can call its ledger-only verdict tool; its read-only-ness is structural —
    # no file-writing tool + the read-only sandbox tier.
    assert mat.config.permission_mode == "default"
    sandbox = (mat.working_dir / ".harness" / "sandbox.toml").read_text(encoding="utf-8")
    assert 'tier = "read-only"' in sandbox
    assert "confirm_unrestricted" not in sandbox


def test_manager_harness_registers_the_decompose_capability_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The manager's leverage is the chorus `decompose` capability — a chorus-only tool with no dream
    # built-in. It is registered into the harness only when the factory has a ledger to bind it to.
    ledger = SqliteLedger.open(":memory:")
    try:
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
            ledger=ledger,
        )
        factory.materialize(Employee(id="moe", name="Moe", role="manager"))
        names = {t.name for t in captured["registry"].list_tools()}
        assert names == {"read_file", "decompose", "submit_task", "assign_task"}
    finally:
        ledger.close()


def test_marketer_harness_registers_the_stage_go_live_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The marketer's ONLY path to a live surface is the `stage_go_live` capability tool (§07/§11): a
    # chorus capability that opens a governance gate, with no dream built-in. It is registered into
    # the harness only when the factory has a ledger to bind it to — fail-closed otherwise.
    ledger = SqliteLedger.open(":memory:")
    try:
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
            ledger=ledger,
        )
        factory.materialize(Employee(id="mira", name="Mira", role="marketer"))
        names = {t.name for t in captured["registry"].list_tools()}
        assert "stage_go_live" in names  # her one gated live surface is wired
        assert (
            "decompose" not in names
        )  # she is not a delegator; go-live is her only capability tool
    finally:
        ledger.close()


def test_integrate_beat_harness_drops_the_decompose_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Structural over-decompose guard (M3 §5): an integrate beat — the manager's task already has
    # children — is materialized WITHOUT `decompose`, so the model can react with submit_task /
    # assign_task but cannot re-decompose (and balloon) a delegated subtree. Brief discipline alone
    # is not enough; under load a manager re-decomposes.
    from chorus.ledger import Task, TaskStatus

    ledger = SqliteLedger.open(":memory:")
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        ledger.employees.create(Employee(id="moe", name="Moe", role="manager"))
        ledger.tasks.submit(Task(id="goal", intent="ship it", status=TaskStatus.TODO))
        ledger.tasks.submit(
            Task(id="kid", intent="a part", status=TaskStatus.TODO, parent_id="goal")
        )
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        factory.materialize(Employee(id="moe", name="Moe", role="manager"), task_id="goal")
        names = {t.name for t in captured["registry"].list_tools()}
        assert "decompose" not in names  # cannot re-decompose a delegated subtree
        assert {"read_file", "submit_task", "assign_task"} <= names  # the reactive toolset remains
    finally:
        ledger.close()


def test_integrate_beat_over_a_complete_subtree_drops_all_mutating_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The strongest over-submit guard (M3 §5): when EVERY child is already done with a passing DoD, the
    # delegated work is complete — the kernel's recommendation is `accept`, so the integrate harness is
    # materialized WITHOUT submit_task/assign_task. The manager literally cannot bolt on redundant work;
    # its only move is to accept. (A live gpt-class manager over-submits even when told to accept — brief
    # discipline is not enough, so the tools are withheld structurally.)
    from chorus.ledger import DodStatus, Task, TaskStatus
    from chorus.outcomes import Verifier

    ledger = SqliteLedger.open(":memory:")
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        ledger.employees.create(Employee(id="moe", name="Moe", role="manager"))
        ledger.tasks.submit(Task(id="goal", intent="ship it", status=TaskStatus.BLOCKED))
        ledger.tasks.submit(
            Task(id="kid", intent="a part", status=TaskStatus.DONE, parent_id="goal")
        )
        dod = ledger.dod.create("kid", Verifier.command("pytest", artifact_class="file"))
        ledger.dod.record_verdict(dod.id, DodStatus.PASSED, verdict={}, run_id=None)
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        factory.materialize(Employee(id="moe", name="Moe", role="manager"), task_id="goal")
        names = {t.name for t in captured["registry"].list_tools()}
        assert "decompose" not in names
        assert (
            "submit_task" not in names and "assign_task" not in names
        )  # cannot over-submit a done subtree
        assert names == {"read_file"}  # only read remains — the manager reviews, then accepts
    finally:
        ledger.close()


def test_reviewer_harness_registers_the_submit_verdict_capability_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The Reviewer's one capability is the chorus `submit_verdict` tool — read-only on the filesystem,
    # it mutates only the ledger DoD verdict. Registered when the factory has a ledger to bind it to.
    ledger = SqliteLedger.open(":memory:")
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        factory.materialize(Employee(id="rob", name="Rob", role="reviewer"))
        names = {t.name for t in captured["registry"].list_tools()}
        assert names == {
            "read_file",
            "submit_verdict",
        }  # read-only inspection + the verdict capability
    finally:
        ledger.close()


def test_reviewer_can_be_materialized_at_the_worker_s_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The reviewer inspects the work IN PLACE: pointed at the worker's worktree as its (read-only)
    # working dir, so the verdict is rendered on the real diff. Its read-only sandbox keeps it look-only.
    factory, _ = _factory(monkeypatch, tmp_path)
    review = factory.materialize(
        Employee(id="rob", name="Rob", role="reviewer"), review_worktree_of="ada"
    )
    assert (
        review.working_dir == tmp_path / "acme" / "worktrees" / "ada"
    )  # ada's worktree, not rob's
    sandbox = (review.working_dir / ".harness" / "sandbox.toml").read_text(encoding="utf-8")
    assert 'tier = "read-only"' in sandbox


def test_manager_brief_is_rehydrated_with_its_team(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A delegating role needs to name valid assignees: the factory appends the live workforce roster to
    # the manager's brief (which the overlays write onto every dream role).
    ledger = SqliteLedger.open(":memory:")
    try:
        from chorus.workforce import Employee as _Emp

        ledger.employees.create(_Emp(id="moe", name="Moe", role="manager"))
        ledger.employees.create(_Emp(id="ada", name="Ada", role="engineer", reports_to="moe"))
        ledger.employees.create(_Emp(id="bob", name="Bob", role="engineer", reports_to="moe"))
        ledger.employees.create(_Emp(id="eve", name="Eve", role="engineer"))
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
            ledger=ledger,
        )
        mat = factory.materialize(ledger.employees.get("moe"))  # type: ignore[arg-type]
        generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text("utf-8")
        assert "ada (engineer)" in generator and "bob (engineer)" in generator
        assert "eve (engineer)" not in generator
        assert "moe" not in generator.split("Your reports")[1]  # the manager isn't its own report
    finally:
        ledger.close()


def test_manager_without_a_ledger_has_no_capability_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # No ledger → the capability tool can't be bound, so it is simply absent (fails closed, no crash).
    factory, captured = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id="moe", name="Moe", role="manager"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert names == {"read_file"}


def test_runner_for_is_a_beat_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory, _ = _factory(monkeypatch, tmp_path)
    runner = factory.runner_for(Employee(id="ada", name="Ada", role="engineer"))
    assert isinstance(runner, BeatRunner)  # the scheduler dispatches through this


def test_unregistered_role_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory, _ = _factory(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not a registered role"):
        factory.materialize(Employee(id="x", name="X", role="ghost"))
