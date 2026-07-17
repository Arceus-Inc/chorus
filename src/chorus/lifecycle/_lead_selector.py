"""Deterministic lead selection for delegated work intake."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dream.contracts.delegation import DelegatedWorkRequest, StaffingBlocked

from chorus.workforce import Employee
from chorus.workforce._ledger import LedgerWorkforce

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger
    from chorus.ledger._models import ManagementProfile

_TERMINAL_TASK_STATUSES = {
    "cancelled",
    "done",
    "rejected",
}
_UNBOUNDED_HEADROOM = 2**63 - 1
_BLOCKED_REASON = "no invokable lead satisfies profile, line, team-size, and budget constraints"


class LeadSelector:
    """Select an authorized lead using stable policy-derived ranking."""

    def __init__(
        self,
        ledger: SqliteLedger,
        *,
        company_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from chorus.budgets import BudgetEnforcer

        self._ledger = ledger
        self._workforce = LedgerWorkforce(ledger.employees)
        self._budgets = BudgetEnforcer(ledger, company_id=company_id)
        self._clock = clock or (lambda: datetime.now(UTC))

    def select(self, request: DelegatedWorkRequest) -> Employee | StaffingBlocked:
        """Return the preferred valid lead or the highest-ranked eligible specialist."""
        now = self._clock()
        candidates = self._eligible_candidates(request, now=now)
        if request.preferred_lead is not None:
            for employee, _profile in candidates:
                if employee.id == request.preferred_lead:
                    return employee

        if not candidates:
            return StaffingBlocked(goal_id=request.goal_id, reason=_BLOCKED_REASON)

        ranked = sorted(
            candidates,
            key=lambda candidate: self._rank(candidate[0], request, now=now),
        )
        return ranked[0][0]

    def _eligible_candidates(
        self, request: DelegatedWorkRequest, *, now: datetime
    ) -> list[tuple[Employee, ManagementProfile]]:
        from chorus.heartbeat._invokability import invokability_block

        direct_counts = Counter(
            {
                requirement.profession: sum(
                    item.count
                    for item in request.requirements
                    if item.coverage == "direct" and item.profession == requirement.profession
                )
                for requirement in request.requirements
                if requirement.coverage == "direct"
            }
        )
        subtree_areas = {
            requirement.outcome_area or requirement.profession
            for requirement in request.requirements
            if requirement.coverage == "subtree"
        }
        requested_team_size = 1 + sum(direct_counts.values()) + len(subtree_areas)
        candidates: list[tuple[Employee, ManagementProfile]] = []
        workforce = self._workforce.list()
        for profile in self._ledger.management_profiles.active_profiles():
            if not profile.can_lead or profile.max_team_size < requested_team_size:
                continue
            if request.max_team_size is not None and requested_team_size > request.max_team_size:
                continue
            if (
                request.spend_limit_cents is not None
                and profile.spend_limit_cents is not None
                and request.spend_limit_cents > profile.spend_limit_cents
            ):
                continue
            employee = self._workforce.get(profile.employee_id)
            if request.lead_professions and employee.role not in request.lead_professions:
                continue
            if invokability_block(self._workforce, employee.id) is not None:
                continue
            if self._budgets.invocation_block(employee.id, now=now) is not None:
                continue
            direct_reports = [report for report in workforce if report.reports_to == employee.id]
            direct_report_counts = Counter(report.role for report in direct_reports)
            if any(
                direct_report_counts[profession] < count
                for profession, count in direct_counts.items()
            ):
                continue
            matched_branches = self._match_subtree_areas(
                request,
                direct_reports=direct_reports,
                workforce=workforce,
                max_depth=profile.max_delegation_depth,
            )
            if matched_branches is None:
                continue
            immediate_professions = set(direct_counts) | {
                branch.role for branch in matched_branches
            }
            if profile.allowed_professions and not immediate_professions.issubset(
                profile.allowed_professions
            ):
                continue
            candidates.append((employee, profile))
        return candidates

    def _match_subtree_areas(
        self,
        request: DelegatedWorkRequest,
        *,
        direct_reports: list[Employee],
        workforce: list[Employee],
        max_depth: int,
    ) -> tuple[Employee, ...] | None:
        grouped: dict[str, Counter[str]] = {}
        for requirement in request.requirements:
            if requirement.coverage != "subtree":
                continue
            area = requirement.outcome_area or requirement.profession
            grouped.setdefault(area, Counter())[requirement.profession] += requirement.count
        if not grouped:
            return ()
        if max_depth < 1:
            return None

        by_manager: dict[str, list[Employee]] = {}
        for employee in workforce:
            if employee.reports_to is not None:
                by_manager.setdefault(employee.reports_to, []).append(employee)
        branch_counts = {
            branch.id: self._subtree_counts(
                branch,
                by_manager=by_manager,
                max_depth=max_depth,
            )
            for branch in direct_reports
        }
        options = {
            area: [
                branch
                for branch in direct_reports
                if all(
                    branch_counts[branch.id][profession] >= count
                    for profession, count in requirements.items()
                )
            ]
            for area, requirements in grouped.items()
        }
        if any(not branches for branches in options.values()):
            return None

        ordered_areas = sorted(options, key=lambda area: (len(options[area]), area))

        def assign(
            index: int, used: set[str], matched: list[Employee]
        ) -> tuple[Employee, ...] | None:
            if index == len(ordered_areas):
                return tuple(matched)
            area = ordered_areas[index]
            for branch in sorted(options[area], key=lambda employee: employee.id):
                if branch.id in used:
                    continue
                result = assign(index + 1, used | {branch.id}, [*matched, branch])
                if result is not None:
                    return result
            return None

        return assign(0, set(), [])

    def _subtree_counts(
        self,
        root: Employee,
        *,
        by_manager: dict[str, list[Employee]],
        max_depth: int,
    ) -> Counter[str]:
        counts: Counter[str] = Counter()
        frontier = [(root, 1)]
        visited: set[str] = set()
        while frontier:
            employee, depth = frontier.pop()
            if employee.id in visited:
                continue
            visited.add(employee.id)
            counts[employee.role] += 1
            if depth < max_depth:
                frontier.extend((report, depth + 1) for report in by_manager.get(employee.id, ()))
        return counts

    def _rank(
        self, employee: Employee, request: DelegatedWorkRequest, *, now: datetime
    ) -> tuple[int, int, int, int, str]:
        requested_professions = set(request.lead_professions) or {
            requirement.profession for requirement in request.requirements
        }
        direct_reports = [
            report for report in self._workforce.list() if report.reports_to == employee.id
        ]
        profession_fit = int(employee.role in requested_professions)
        report_coverage = sum(
            min(
                sum(report.role == requirement.profession for report in direct_reports),
                requirement.count,
            )
            for requirement in request.requirements
        )
        observed_load = sum(
            task.assignee_employee_id == employee.id
            and task.status.value not in _TERMINAL_TASK_STATUSES
            for task in self._ledger.tasks.all()
        )
        headroom = self._budget_headroom(employee.id, now=now)
        return (-profession_fit, -report_coverage, observed_load, -headroom, employee.id)

    def _budget_headroom(self, employee_id: str, *, now: datetime) -> int:
        from chorus.budgets import BudgetWindow
        from chorus.budgets._window import window_start
        from chorus.ledger import BudgetScope

        policies = [
            policy
            for policy in self._ledger.budget_policies.by_scope(BudgetScope.EMPLOYEE, employee_id)
            if policy.metric == "cost_cents"
        ]
        if not policies:
            return _UNBOUNDED_HEADROOM
        return min(
            policy.amount
            - self._ledger.cost_events.spent_cents(
                employee_id,
                since=window_start(BudgetWindow(policy.window_kind), now),
            )
            for policy in policies
        )


__all__ = ["LeadSelector"]
