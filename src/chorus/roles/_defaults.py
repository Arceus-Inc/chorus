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

# The Engineer, Reviewer, and Manager each own a dedicated package under chorus_employee/. The kernel
# default set sources them from there — single source, no drift — rather than re-declaring them here.
# Submodule imports (not the chorus_employee package root) keep this edge cycle-free. PM / Analyst are
# still declared inline below until they grow their own packages.
from chorus_employee.engineer import engineer_plugin
from chorus_employee.manager import manager_plugin
from chorus_employee.reviewer import reviewer_plugin

_PM_BRIEF = "You produce a spec/decision artifact, persisted somewhere a Reviewer can verify it."
_ANALYST_BRIEF = "You produce a data finding, persisted somewhere a Reviewer can verify it."


def default_roles() -> tuple[RolePlugin, ...]:
    """The canonical v0 workforce roles, registered at boot (spec 06 §2).

    A consumer adds a sixth role with ``chorus.register_role(...)`` — never by
    editing the kernel (spec 09 §1).
    """
    return (
        engineer_plugin(),
        reviewer_plugin(),
        manager_plugin(),
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
