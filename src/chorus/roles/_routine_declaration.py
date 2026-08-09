"""A role plugin's standing schedule (spec 13 §5.1).

A :class:`RoutineDeclaration` is recurring work a *role* carries — "a PM files a planning review every
Monday 09:00". It is plain data: the kernel-side :func:`chorus.cron.reconcile_declared_routines` turns
declarations into real routines (create + revision 1 + trigger), keyed by ``routine_key`` so re-running
is idempotent. Declarations live with the plugin (on :class:`~chorus.roles.RolePlugin.declared_routines`)
and are validated fail-closed at registration — a bad cron or an inline secret never schedules.
"""

from __future__ import annotations

from dataclasses import dataclass

from chorus.ledger import RoutineCatchUp, RoutineConcurrency, RoutineStatus, RoutineTarget


@dataclass(frozen=True)
class RoutineDeclaration:
    """One routine a role provisions for each of its employees, resolved by ``routine_key``."""

    routine_key: str
    intent_template: str
    schedule: str  # 5-field cron expression
    target: RoutineTarget = RoutineTarget.SPAWN_TASK
    concurrency: RoutineConcurrency = RoutineConcurrency.COALESCE
    catch_up: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED
    env: dict[str, str] | None = None
    initial_status: RoutineStatus = RoutineStatus.ACTIVE


__all__ = ["RoutineDeclaration"]
