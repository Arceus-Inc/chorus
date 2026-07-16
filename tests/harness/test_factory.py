"""EmployeeHarnessFactory — the org's one role-faithful materializer (spec 06 §2 → dream seam).

dream's harness build is stubbed so the role → harness translation is tested without a provider; the
worktree side-effects run on real git in a temp dir.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatRunner
from chorus.ledger import (
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    ManagementProfile,
    SqliteLedger,
    Task,
    TaskStatus,
    Team,
    TeamMember,
    TeamMembershipRole,
    TeamStatus,
)
from chorus.roles import RoleRegistry, default_roles
from chorus.verification import SYSTEM_VERIFIER
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


def _seed_delegation(ledger: SqliteLedger, *, child_status: TaskStatus | None = None) -> Employee:
    lead = Employee(id="moe", name="Moe", role="backend_engineer")
    worker = Employee(id="ada", name="Ada", role="backend_engineer", reports_to=lead.id)
    ledger.employees.create(lead)
    ledger.employees.create(worker)
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id=lead.id,
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            max_delegation_depth=1,
            max_team_size=3,
            allowed_professions=("backend_engineer",),
            version=1,
        )
    )
    ledger.teams.create(
        Team(
            id="team-goal",
            name="Goal Team",
            lead_employee_id=lead.id,
            created_by="operator",
            status=TeamStatus.ACTIVE,
        )
    )
    for employee_id, membership_role in (
        (lead.id, TeamMembershipRole.LEAD),
        (worker.id, TeamMembershipRole.MEMBER),
    ):
        ledger.team_members.add(
            TeamMember(
                team_id="team-goal",
                employee_id=employee_id,
                source_manager_id=lead.id,
                membership_role=membership_role,
            )
        )
    ledger.tasks.submit(
        Task(
            id="goal",
            intent="ship it",
            status=TaskStatus.BLOCKED if child_status is not None else TaskStatus.TODO,
            execution_mode=ExecutionMode.DELEGATION,
            team_id="team-goal",
            assignee_employee_id=lead.id,
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id="goal",
            team_id="team-goal",
            lead_employee_id=lead.id,
            management_profile_version=1,
            max_depth=1,
            max_team_size=3,
            objective_rubric="integrate the delegated subtree",
            status=(
                DelegationContractStatus.INTEGRATING
                if child_status is not None
                else DelegationContractStatus.DELEGATED
            ),
        )
    )
    if child_status is not None:
        ledger.tasks.submit(
            Task(
                id="kid",
                intent="a part",
                status=child_status,
                parent_id="goal",
                assignee_employee_id=worker.id,
            )
        )
    return lead


def test_backend_engineer_materializes_a_writable_harness_in_its_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="backend_engineer"))
    # the engineer works confined to its own branch-isolated worktree under the org root
    assert mat.working_dir == tmp_path / "acme" / "worktrees" / "ada"
    assert mat.workspace is not None
    names = {t.name for t in captured["registry"].list_tools()}
    assert names == {
        "read_file",
        "read_offloaded",
        "write_file",
        "bash",
        "git",
        "todo_write",
        "skill",
        "memory_search",
        "memory_get",
        "recall",
        "get_run",
        "test_evidence",
        "test_red",
        "secret_scan",
        "code_quality",
        "lattice_context",
        "lattice_packet",
        "lattice_apply",
        "skill_manage",
    }
    assert mat.config.permission_mode == "acceptEdits"
    assert captured["max_turns"] == 18  # the engine scalars come from the role too
    assert captured["working_memory"] is True
    assert mat.runner._subagent_evidence == {
        "test_author": ("test_plan.json", {"authored": True}, False),
        "code_reviewer": ("review_verdict.json", {"cleared": True}, True),
    }


def test_role_registry_registers_the_read_file_offload_companion() -> None:
    from chorus_harness._factory import _role_registry

    names = {tool.name for tool in _role_registry(("read_file",)).list_tools()}
    assert names == {"read_file", "read_offloaded"}


def test_engineer_role_overlays_admit_read_memory_for_read_only_heads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The evaluator is the read-only head that keeps tools, so it admits the safe read-memory surfaces
    # (memory_search/memory_get/working_memory_read) to verify with. The planner is deliberately
    # TOOLLESS (`tools = []`) — given tools + tool_choice="auto", weaker models emit a tool call with
    # zero text and `run_task` fails with "planner reply missing <spec>" (see write_role_overlays). The
    # generator runs tools=null (no `tools =` line), so it sees the full role toolset.
    factory, _ = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="backend_engineer"))

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
    mat = factory.materialize(Employee(id="ada", name="Ada", role="backend_engineer"))
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


def test_system_verifier_materializes_a_read_only_harness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize_verifier(SYSTEM_VERIFIER, task_id="review", worktree_owner_id="ada")
    # the headline win: a reviewer is read-only EVERYWHERE — not just in chat. Its only tool with no
    # ledger is read_file plus its scratch-confined offload companion (submit_verdict needs a ledger to
    # bind to, registered in the ledger-bound test).
    names = {t.name for t in captured["registry"].list_tools()}
    assert names == {"read_file", "read_offloaded"}
    # DEFAULT permission so it can call its ledger-only verdict tool; its read-only-ness is structural —
    # no file-writing tool + the read-only sandbox tier.
    assert mat.config.permission_mode == "default"
    sandbox = (mat.working_dir / ".harness" / "sandbox.toml").read_text(encoding="utf-8")
    assert 'tier = "read-only"' in sandbox
    assert "confirm_unrestricted" not in sandbox


def test_delegation_harness_registers_the_decompose_capability_tool(
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
        lead = _seed_delegation(ledger)
        factory.materialize(lead, task_id="goal")
        names = {t.name for t in captured["registry"].list_tools()}
        assert names == {
            "read_file",
            "read_offloaded",
            "decompose",
            "team_read",
            "staffing_request",
        }
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
    from chorus.ledger import TaskStatus

    ledger = SqliteLedger.open(":memory:")
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        lead = _seed_delegation(ledger, child_status=TaskStatus.TODO)
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        factory.materialize(lead, task_id="goal")
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
    from chorus.ledger import DodStatus, TaskStatus
    from chorus.outcomes import Verifier

    ledger = SqliteLedger.open(":memory:")
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        lead = _seed_delegation(ledger, child_status=TaskStatus.DONE)
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
        factory.materialize(lead, task_id="goal")
        names = {t.name for t in captured["registry"].list_tools()}
        assert "decompose" not in names
        assert (
            "submit_task" not in names and "assign_task" not in names
        )  # cannot over-submit a done subtree
        assert names == {
            "read_file",
            "read_offloaded",
            "team_read",
        }  # only reads remain before acceptance
    finally:
        ledger.close()


def test_system_verifier_harness_registers_the_submit_verdict_capability_tool(
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
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        factory.materialize_verifier(SYSTEM_VERIFIER, task_id="review", worktree_owner_id="ada")
        names = {t.name for t in captured["registry"].list_tools()}
        assert names == {
            "read_file",
            "read_offloaded",
            "submit_verdict",
        }  # read-only inspection + the verdict capability
    finally:
        ledger.close()


def test_system_verifier_is_materialized_at_the_worker_s_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The reviewer inspects the work IN PLACE: pointed at the worker's worktree as its (read-only)
    # working dir, so the verdict is rendered on the real diff. Its read-only sandbox keeps it look-only.
    factory, _ = _factory(monkeypatch, tmp_path)
    review = factory.materialize_verifier(
        SYSTEM_VERIFIER, task_id="review", worktree_owner_id="ada"
    )
    assert (
        review.working_dir == tmp_path / "acme" / "worktrees" / "ada"
    )  # ada's worktree, not a system-principal worktree
    sandbox = (review.working_dir / ".harness" / "sandbox.toml").read_text(encoding="utf-8")
    assert 'tier = "read-only"' in sandbox


def test_delegation_brief_is_rehydrated_with_its_team(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A delegating role needs to name valid assignees: the factory appends the live workforce roster to
    # the manager's brief (which the overlays write onto every dream role).
    ledger = SqliteLedger.open(":memory:")
    try:
        from chorus.workforce import Employee as _Emp

        lead = _seed_delegation(ledger)
        ledger.employees.create(
            _Emp(id="bob", name="Bob", role="backend_engineer", reports_to="moe")
        )
        ledger.employees.create(_Emp(id="eve", name="Eve", role="backend_engineer"))
        ledger.team_members.add(
            TeamMember(
                team_id="team-goal",
                employee_id="bob",
                source_manager_id="moe",
                membership_role=TeamMembershipRole.MEMBER,
            )
        )
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
        mat = factory.materialize(lead, task_id="goal")
        generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text("utf-8")
        assert "ada (backend_engineer)" in generator
        assert "bob (backend_engineer)" in generator
        assert "eve (engineer)" not in generator
        assert "moe" not in generator.split("Your reports")[1]  # the manager isn't its own report
    finally:
        ledger.close()


@pytest.mark.parametrize(
    ("active", "can_lead", "expects_director_guidance"),
    ((True, True, True), (False, True, False), (True, False, False)),
)
def test_team_roster_uses_management_authority_to_identify_manager_reports(
    active: bool, can_lead: bool, expects_director_guidance: bool
) -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        director = Employee(id="ceo", name="Casey", role="ceo")
        specialist_lead = Employee(
            id="backend-lead",
            name="Blair",
            role="backend_engineer",
            reports_to=director.id,
        )
        ledger.employees.create(director)
        ledger.employees.create(specialist_lead)
        ledger.management_profiles.upsert(
            ManagementProfile(
                employee_id=specialist_lead.id,
                granted_by_user_id="operator",
                active=active,
                can_lead=can_lead,
                max_delegation_depth=1,
                max_team_size=3,
                allowed_professions=("backend_engineer",),
            )
        )

        roster = _factory_mod._team_roster(ledger, exclude=director.id)

        assert ("You are a director" in roster) is expects_director_guidance
        assert ("manager reports (backend-lead)" in roster) is expects_director_guidance
    finally:
        ledger.close()


def test_management_profile_without_a_delegation_task_keeps_delivery_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = SqliteLedger.open(":memory:")
    lead = _seed_delegation(ledger)
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
    factory.materialize(lead)
    names = {t.name for t in captured["registry"].list_tools()}
    assert not {"decompose", "submit_task", "assign_task"}.intersection(names)
    assert {"write_file", "bash", "git"} <= names
    ledger.close()


async def test_tdd_review_delivery_task_gates_parent_production_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = SqliteLedger.open(":memory:")
    _seed_delegation(ledger)
    worker = ledger.employees.get("ada")
    assert worker is not None
    ledger.tasks.submit(
        Task(
            id="delivery",
            intent="implement the backend",
            status=TaskStatus.TODO,
            execution_mode=ExecutionMode.DELIVERY,
            assignee_employee_id=worker.id,
        )
    )
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

    materialized = factory.materialize(worker, task_id="delivery")
    write_file = captured["registry"].get("write_file")
    assert write_file is not None
    result = await write_file.execute(
        {"path": "backend/service.py", "content": "implemented = True\n"},
        ToolExecutionContext(
            working_dir=materialized.working_dir,
            session_id="session",
            metadata={"dream.role": "generator"},
        ),
    )

    assert result.is_error is True
    assert result.metadata["root_cause"] == "strict_tdd_red_not_authorized"
    assert captured["registry"].get("spawn_subagent") is not None
    ledger.close()


def test_runner_for_is_a_beat_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory, _ = _factory(monkeypatch, tmp_path)
    runner = factory.runner_for(Employee(id="ada", name="Ada", role="backend_engineer"))
    assert isinstance(runner, BeatRunner)  # the scheduler dispatches through this


def test_unregistered_role_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory, _ = _factory(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not a registered role"):
        factory.materialize(Employee(id="x", name="X", role="ghost"))
