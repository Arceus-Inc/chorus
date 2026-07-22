"""Governed CEO workforce proposals and atomic human-approved formation."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from chorus.ids import mint_id
from chorus.ledger import (
    ActivityVerb,
    BudgetPolicy,
    BudgetScope,
    Ledger,
    ManagementProfile,
    PlannedEmployee,
    StaffingRequest,
    StaffingRequestStatus,
    TaskStatus,
    WorkforcePlan,
    WorkforcePlanDraft,
    WorkforcePlanStatus,
)
from chorus.lifecycle._audit import record_activity
from chorus.roles import RoleRegistry
from chorus.workforce import Employee, EmployeeStatus, Workforce

_PLAN_PROFESSIONS = frozenset(
    {
        "analyst",
        "backend_engineer",
        "designer",
        "frontend_engineer",
        "marketer",
        "pm",
    }
)


class WorkforcePlanService:
    """Validate, persist, revise, and atomically apply workforce plans."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        workforce: Workforce,
        roles: RoleRegistry,
        max_org_depth: int = 2,
    ) -> None:
        if max_org_depth < 1:
            raise ValueError("max_org_depth must be at least one")
        self._ledger = ledger
        self._workforce = workforce
        self._roles = roles
        self._max_org_depth = max_org_depth

    def propose(
        self,
        draft: WorkforcePlanDraft,
        *,
        proposed_by_employee_id: str,
        staffing_request_id: str | None = None,
        proposed_in_task_id: str | None = None,
    ) -> WorkforcePlan:
        proposer = self._ledger.employees.get(proposed_by_employee_id)
        if (
            proposer is None
            or proposer.role != "ceo"
            or proposer.status in {EmployeeStatus.PENDING, EmployeeStatus.TERMINATED}
        ):
            raise ValueError("workforce plans require an active CEO proposer")
        pending = next(
            (
                plan
                for plan in self._ledger.workforce_plans.list()
                if plan.proposed_by_employee_id == proposer.id
                and plan.status is WorkforcePlanStatus.PROPOSED
            ),
            None,
        )
        if pending is not None:
            raise ValueError(
                f"CEO already has a proposed workforce plan {pending.id!r}; "
                "a human must approve, reject, or revise it before another proposal"
            )
        staffing_request = self._validate_staffing_amendment(
            draft,
            staffing_request_id=staffing_request_id,
        )
        self._validate(draft, root_employee_id=proposer.id)
        plan = WorkforcePlan(
            id=mint_id(),
            revision=1,
            status=WorkforcePlanStatus.PROPOSED,
            proposed_by_employee_id=proposer.id,
            draft=draft,
            staffing_request_id=staffing_request_id,
            proposed_in_task_id=proposed_in_task_id,
        )
        with self._ledger.transaction():
            persisted = self._ledger.workforce_plans.create(plan)
            if staffing_request is not None:
                self._ledger.staffing_requests.link_plan(staffing_request.id, plan.id)
            record_activity(
                self._ledger,
                verb=ActivityVerb.WORKFORCE_PLAN_PROPOSED,
                subject_kind="workforce_plan",
                subject_id=plan.id,
                actor_employee_id=proposer.id,
                payload={"revision": 1},
            )
        return persisted

    def reject(self, plan_id: str, *, rejected_by_user_id: str) -> WorkforcePlan:
        actor = _require_human_actor(rejected_by_user_id)
        plan = self._require_latest_proposed(plan_id)
        with self._ledger.transaction():
            persisted = self._ledger.workforce_plans.update_status(
                plan.id,
                plan.revision,
                WorkforcePlanStatus.REJECTED,
                decided_by_user_id=actor,
            )
            record_activity(
                self._ledger,
                verb=ActivityVerb.WORKFORCE_PLAN_REJECTED,
                subject_kind="workforce_plan",
                subject_id=plan.id,
                actor_user_id=actor,
                payload={"revision": plan.revision},
            )
        return persisted

    def revise(
        self,
        plan_id: str,
        draft: WorkforcePlanDraft,
        *,
        revised_by_user_id: str,
    ) -> WorkforcePlan:
        actor = _require_human_actor(revised_by_user_id)
        current = self._require_latest_proposed(plan_id)
        self._validate_staffing_amendment(
            draft,
            staffing_request_id=current.staffing_request_id,
        )
        self._validate(draft, root_employee_id=current.proposed_by_employee_id)
        revision = current.revision + 1
        revised = WorkforcePlan(
            id=current.id,
            revision=revision,
            status=WorkforcePlanStatus.PROPOSED,
            proposed_by_employee_id=current.proposed_by_employee_id,
            revised_by_user_id=actor,
            draft=draft,
            staffing_request_id=current.staffing_request_id,
            proposed_in_task_id=current.proposed_in_task_id,
        )
        with self._ledger.transaction():
            self._ledger.workforce_plans.update_status(
                current.id, current.revision, WorkforcePlanStatus.SUPERSEDED
            )
            persisted = self._ledger.workforce_plans.create(revised)
            record_activity(
                self._ledger,
                verb=ActivityVerb.WORKFORCE_PLAN_REVISED,
                subject_kind="workforce_plan",
                subject_id=plan_id,
                actor_user_id=actor,
                payload={"revision": revision, "supersedes": current.revision},
            )
        return persisted

    def approve(self, plan_id: str, *, approved_by_user_id: str) -> WorkforcePlan:
        actor = _require_human_actor(approved_by_user_id)
        plan = self._require_latest_proposed(plan_id)
        staffing_request = self._validate_staffing_amendment(
            plan.draft,
            staffing_request_id=plan.staffing_request_id,
        )
        self._validate(plan.draft, root_employee_id=plan.proposed_by_employee_id)
        ordered = self._topological_employees(
            plan.draft, root_employee_id=plan.proposed_by_employee_id
        )
        # A plan ``ref`` is a CEO-authored, in-plan handle used only to wire reporting lines and
        # grants within one proposal (e.g. the model writes "new-jules"). It must NOT leak into the
        # ledger as the permanent employee id. Mint a clean, human id from the person's real name
        # and remap every in-plan reference (``reports_to_ref``, grant ``employee_ref``) through it;
        # an existing employee id (a current manager like the CEO) passes through unchanged.
        taken_ids = {employee.id for employee in self._ledger.employees.list()}
        ref_to_id: dict[str, str] = {}
        for planned in ordered:
            employee_id = _mint_employee_id(planned.name, taken_ids)
            ref_to_id[planned.ref] = employee_id
            taken_ids.add(employee_id)

        def _resolve(ref: str) -> str:
            """Map an in-plan new-hire ref to its minted id; an existing employee id passes through."""
            return ref_to_id.get(ref, ref)

        with self._ledger.transaction():
            for planned in ordered:
                employee_id = ref_to_id[planned.ref]
                self._ledger.employees.create(
                    Employee(
                        id=employee_id,
                        name=planned.name,
                        role=planned.profession,
                        reports_to=_resolve(planned.reports_to_ref),
                        status=EmployeeStatus.IDLE,
                    )
                )
                # OM-1 (found live): a formed org must heartbeat like a facade-hired one —
                # provision the role's declared routines exactly as ``Chorus.hire`` does.
                plugin = self._roles.get(planned.profession)  # _validate pinned it exists
                if plugin.declared_routines:
                    from chorus.cron import reconcile_declared_routines

                    reconcile_declared_routines(
                        self._ledger,
                        employee_id=employee_id,
                        declarations=plugin.declared_routines,
                    )
                if planned.budget_cents is not None:
                    self._ledger.budget_policies.create(
                        BudgetPolicy(
                            id=mint_id(),
                            scope_type=BudgetScope.EMPLOYEE,
                            scope_id=employee_id,
                            amount=planned.budget_cents,
                        )
                    )
            for grant in plan.draft.management_grants:
                grant_employee_id = _resolve(grant.employee_ref)
                # A grant may re-affirm an employee who already holds a profile (the CEO always
                # does; so do leads carried across an amendment). The profile is versioned and the
                # store requires the version to strictly increase, so bump past the current one —
                # a fresh grant starts at 1.
                current = self._ledger.management_profiles.get(grant_employee_id)
                next_version = current.version + 1 if current is not None else 1
                self._ledger.management_profiles.upsert(
                    ManagementProfile(
                        employee_id=grant_employee_id,
                        granted_by_user_id=actor,
                        active=True,
                        can_lead=grant.can_lead,
                        can_subdelegate=grant.can_subdelegate,
                        max_delegation_depth=grant.max_delegation_depth,
                        max_team_size=grant.max_team_size,
                        allowed_professions=grant.allowed_professions,
                        spend_limit_cents=grant.spend_limit_cents,
                        version=next_version,
                    )
                )
            persisted = self._ledger.workforce_plans.update_status(
                plan.id,
                plan.revision,
                WorkforcePlanStatus.APPLIED,
                decided_by_user_id=actor,
            )
            # A proposal task is done when its proposal is decided (free-run, found live):
            # without this the formation task re-beats forever after its plan was applied.
            if plan.proposed_in_task_id is not None:
                origin = self._ledger.tasks.get(plan.proposed_in_task_id)
                if origin is not None and origin.status.value not in {
                    "done",
                    "cancelled",
                    "rejected",
                }:
                    self._ledger.tasks.set_status(origin.id, TaskStatus.DONE)
            record_activity(
                self._ledger,
                verb=ActivityVerb.WORKFORCE_PLAN_APPLIED,
                subject_kind="workforce_plan",
                subject_id=plan.id,
                actor_user_id=actor,
                payload={
                    "revision": plan.revision,
                    "employees": len(plan.draft.employees),
                    "management_grants": len(plan.draft.management_grants),
                },
            )
            if staffing_request is not None:
                self._ledger.staffing_requests.fulfil(staffing_request.id, plan.id)
                record_activity(
                    self._ledger,
                    verb=ActivityVerb.STAFFING_REQUEST_FULFILLED,
                    subject_kind="staffing_request",
                    subject_id=staffing_request.id,
                    actor_user_id=actor,
                    payload={"workforce_plan_id": plan.id},
                )
        return persisted

    def _validate(self, draft: WorkforcePlanDraft, *, root_employee_id: str) -> None:
        root = self._ledger.employees.get(root_employee_id)
        if root is None or root.role != "ceo":
            raise ValueError("workforce plan root must be an existing CEO")
        refs = [employee.ref for employee in draft.employees]
        if len(refs) != len(set(refs)):
            raise ValueError("workforce plan employee refs must be unique")
        # Identity dedup (found live 2026-07-19): an expansion that re-lists someone who already
        # exists — same name, new slug — created idle "ghost" duplicates (two Averys, two Jordans).
        # Enforce name-uniqueness across the live org and within the plan: to add capacity you hire a
        # NEW distinct person, you never re-hire an existing name.
        existing_names = {
            e.name.strip().casefold()
            for e in self._ledger.employees.list()
            if e.status not in {EmployeeStatus.TERMINATED, EmployeeStatus.PENDING}
        }
        lead_refs = {grant.employee_ref for grant in draft.management_grants if grant.can_lead}
        seen_names: set[str] = set()
        for employee in draft.employees:
            if self._ledger.employees.get(employee.ref) is not None:
                raise ValueError(f"employee ref {employee.ref!r} already exists")
            name_key = employee.name.strip().casefold()
            if not name_key:
                raise ValueError("every hire needs a real given name")
            if name_key in existing_names:
                raise ValueError(
                    f"an employee named {employee.name!r} already exists — add NEW distinct people "
                    "with real given names, or reference the existing employee; never re-hire a duplicate"
                )
            if name_key in seen_names:
                raise ValueError(f"duplicate employee name {employee.name!r} within the plan")
            seen_names.add(name_key)
            # Only leads report to the CEO (found live: pm ICs hung directly off the CEO). A new hire
            # whose manager is the CEO must itself carry a lead grant in this plan.
            if employee.reports_to_ref == root_employee_id and employee.ref not in lead_refs:
                raise ValueError(
                    f"employee {employee.name!r} reports to the CEO but is not a lead — only leads "
                    "report to the CEO; place individual contributors under their pod lead"
                )
            if (
                employee.profession not in _PLAN_PROFESSIONS
                or employee.profession not in self._roles
            ):
                hireable = sorted(_PLAN_PROFESSIONS & set(self._roles.names()))
                raise ValueError(
                    f"profession {employee.profession!r} is not hireable; use one of {hireable}"
                )
        planned = {employee.ref: employee for employee in draft.employees}
        depths = self._depths(
            planned,
            root_employee_id=root_employee_id,
        )
        if max(depths.values(), default=0) > self._max_org_depth:
            raise ValueError(f"workforce plan depth exceeds maximum {self._max_org_depth}")

        grants = {grant.employee_ref: grant for grant in draft.management_grants}
        if len(grants) != len(draft.management_grants):
            raise ValueError("management grant employee refs must be unique")
        known_refs = set(planned) | {root_employee_id}
        unknown_grants = set(grants) - known_refs
        if unknown_grants:
            raise ValueError(
                f"management grant references unknown employees: {sorted(unknown_grants)}"
            )
        direct_reports: dict[str, list[str]] = defaultdict(list)
        professions = {root_employee_id: root.role} | {
            ref: employee.profession for ref, employee in planned.items()
        }
        for employee in draft.employees:
            direct_reports[employee.reports_to_ref].append(employee.ref)
        for manager_ref, report_refs in direct_reports.items():
            grant = grants.get(manager_ref) or self._ledger.management_profiles.get(manager_ref)
            if grant is None or not grant.can_lead:
                raise ValueError(f"manager {manager_ref!r} requires a lead management grant")
            report_professions = Counter(professions[ref] for ref in report_refs)
            if grant.allowed_professions and not set(report_professions).issubset(
                grant.allowed_professions
            ):
                raise ValueError(
                    f"management grant for {manager_ref!r} does not cover direct-report professions"
                )
            if grant.max_team_size < 1 + len(report_refs):
                raise ValueError(f"management grant for {manager_ref!r} has insufficient team size")
            remaining_depth = self._max_org_depth - depths.get(manager_ref, 0)
            if grant.max_delegation_depth > remaining_depth:
                raise ValueError(
                    f"management grant for {manager_ref!r} exceeds remaining org depth"
                )
        for grant in draft.management_grants:
            invalid = set(grant.allowed_professions) - _PLAN_PROFESSIONS
            if invalid:
                raise ValueError(
                    f"management grant names non-hireable professions: {sorted(invalid)}"
                )

    def _depths(
        self,
        planned: dict[str, PlannedEmployee],
        *,
        root_employee_id: str,
    ) -> dict[str, int]:
        depths = {root_employee_id: 0}
        visiting: set[str] = set()

        def visit(employee_ref: str) -> int:
            if employee_ref in depths:
                return depths[employee_ref]
            if employee_ref in visiting:
                raise ValueError("workforce plan reporting cycle detected")
            employee = planned.get(employee_ref)
            if employee is None:
                existing = self._ledger.employees.get(employee_ref)
                if existing is None or existing.reports_to is None:
                    raise ValueError(
                        f"workforce plan reporting line references unknown employee {employee_ref!r}"
                    )
                visiting.add(employee_ref)
                depth = visit(existing.reports_to) + 1
                visiting.remove(employee_ref)
                depths[employee_ref] = depth
                return depth
            visiting.add(employee_ref)
            manager_ref = employee.reports_to_ref
            depth = visit(manager_ref) + 1
            visiting.remove(employee_ref)
            depths[employee_ref] = depth
            return depth

        for employee_ref in planned:
            visit(employee_ref)
        return depths

    def _topological_employees(
        self, draft: WorkforcePlanDraft, *, root_employee_id: str
    ) -> list[PlannedEmployee]:
        planned = {employee.ref: employee for employee in draft.employees}
        depths = self._depths(planned, root_employee_id=root_employee_id)
        return sorted(draft.employees, key=lambda employee: (depths[employee.ref], employee.ref))

    def _validate_staffing_amendment(
        self,
        draft: WorkforcePlanDraft,
        *,
        staffing_request_id: str | None,
    ) -> StaffingRequest | None:
        if staffing_request_id is None:
            return None
        request = self._ledger.staffing_requests.get(staffing_request_id)
        if request is None or request.status is not StaffingRequestStatus.OPEN:
            raise ValueError("staffing amendment requires an open staffing request")
        requested = Counter({need.profession: need.count for need in request.needs})
        proposed = Counter(employee.profession for employee in draft.employees)
        if (
            proposed != requested
            or any(
                employee.reports_to_ref != request.requested_by_employee_id
                for employee in draft.employees
            )
            or draft.management_grants
            or request.goal_id not in draft.source_goal_ids
        ):
            raise ValueError(
                "staffing amendment must exactly cover the request without expanding authority"
            )
        return request

    def _require_latest_proposed(self, plan_id: str) -> WorkforcePlan:
        plan = self._ledger.workforce_plans.latest(plan_id)
        if plan is None:
            raise ValueError(f"no such workforce plan: {plan_id!r}")
        if plan.status is not WorkforcePlanStatus.PROPOSED:
            raise ValueError(f"workforce plan {plan_id!r} is {plan.status.value!r}, not proposed")
        return plan


def _require_human_actor(actor_user_id: str) -> str:
    actor = actor_user_id.strip()
    if not actor:
        raise ValueError("human actor user id is required")
    return actor


def _slugify_name(name: str) -> str:
    """A clean id fragment from a person's name: lowercase, latin-alnum runs joined by ``-``."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().casefold()).strip("-")


def _mint_employee_id(name: str, taken: set[str]) -> str:
    """A stable, human-readable permanent employee id derived from ``name``, unique against ``taken``.

    The CEO-authored plan ``ref`` is only an in-plan handle (e.g. "new-jules"); the permanent id is
    derived from the person's real name instead — "Jules" -> ``jules``, "Mary Jane" -> ``mary-jane`` —
    so the ledger reads like a real roster. Falls back to a minted id for a name with no latin
    alphanumerics, and disambiguates a collision with a short suffix.
    """
    base = _slugify_name(name) or f"emp-{mint_id()[:8]}"
    if base not in taken:
        return base
    return f"{base}-{mint_id()[:4]}"


__all__ = ["WorkforcePlanService"]
