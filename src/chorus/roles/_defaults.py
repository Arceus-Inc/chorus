"""The v0 role plugins (spec 06 §2 table).

| Role      | Toolset leans            | DoD (verifier)          | Outcome              |
|-----------|--------------------------|-------------------------|----------------------|
| Engineer  | repo-write, run gates    | Command (CI/tests exit0)| PR opened, CI green  |
| Reviewer  | read-only                | renders the verdict     | approve/block        |
| Manager   | ledger-write (decompose) | children done+integrated| a completed subtree  |
| Product/PM| read + write docs        | AgentReview (Reviewer)  | spec/decision        |
| Analyst   | read + data tools        | AgentReview (Reviewer)  | a data finding       |

Reviewer is load-bearing, not a luxury (B3.2): it is the verifier for all
judgment-class work, so it must ship at M3 with the first non-code role.
"""

from __future__ import annotations

from chorus.outcomes import Verifier
from chorus.roles._manifest import MemoryScope, PermissionMode, RoleManifest
from chorus.roles._plugin import RolePlugin

_ENGINEER_BRIEF = (
    "You implement and ship changes. Make the smallest change that satisfies the task. "
    "Definition of done: the verifier on the task must pass (tests + CI green). "
    "House rules: never force-push; leave a PR link in the final comment."
)
_REVIEWER_BRIEF = "You render an approve/block verdict on a diff against the task's rubric."
_MANAGER_BRIEF = "You decompose work, dispatch children, and integrate their completed subtree."
_PM_BRIEF = "You produce a spec/decision artifact, persisted somewhere a Reviewer can verify it."
_ANALYST_BRIEF = "You produce a data finding, persisted somewhere a Reviewer can verify it."


def default_roles() -> tuple[RolePlugin, ...]:
    """The canonical v0 workforce roles, registered at boot (spec 06 §2).

    A consumer adds a sixth role with ``chorus.register_role(...)`` — never by
    editing the kernel (spec 09 §1).
    """
    return (
        RolePlugin(
            name="engineer",
            manifest=RoleManifest(
                system_prompt=_ENGINEER_BRIEF,
                tools=("read_file", "write_file", "run_command", "git"),
                permission_mode=PermissionMode.ACCEPT_EDITS,
                memory_scope=MemoryScope.PROJECT,
            ),
            dod_generator=lambda intent: Verifier.command(
                "pytest -q && ruff check .", artifact_class="pr"
            ),
            outcome_kind="pr",
        ),
        RolePlugin(
            name="reviewer",
            manifest=RoleManifest(
                system_prompt=_REVIEWER_BRIEF,
                tools=("read_file",),
                permission_mode=PermissionMode.PLAN,
                memory_scope=MemoryScope.PROJECT,
            ),
            dod_generator=lambda intent: Verifier.human_approval(artifact_class="verdict"),
            outcome_kind="verdict",
        ),
        RolePlugin(
            name="manager",
            manifest=RoleManifest(
                system_prompt=_MANAGER_BRIEF,
                tools=("read_file", "submit_task", "assign_task"),
                permission_mode=PermissionMode.DEFAULT,
                memory_scope=MemoryScope.TEAM,
            ),
            dod_generator=lambda intent: Verifier.agent_review(
                rubric="all children terminal and integrated", artifact_class="subtree"
            ),
            outcome_kind="subtree",
        ),
        RolePlugin(
            name="pm",
            manifest=RoleManifest(
                system_prompt=_PM_BRIEF,
                tools=("read_file", "write_file"),
                permission_mode=PermissionMode.DEFAULT,
                memory_scope=MemoryScope.PROJECT,
            ),
            dod_generator=lambda intent: Verifier.agent_review(artifact_class="spec"),
            outcome_kind="doc",
        ),
        RolePlugin(
            name="analyst",
            manifest=RoleManifest(
                system_prompt=_ANALYST_BRIEF,
                tools=("read_file", "query_data"),
                permission_mode=PermissionMode.PLAN,
                memory_scope=MemoryScope.PROJECT,
            ),
            dod_generator=lambda intent: Verifier.agent_review(artifact_class="finding"),
            outcome_kind="finding",
        ),
    )


__all__ = ["default_roles"]
