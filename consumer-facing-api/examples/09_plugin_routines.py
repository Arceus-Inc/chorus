"""09 — plugin-declared routines: roles that schedule themselves.  OFFLINE: no model, no creds.

A role can carry its own standing schedule. Hiring an employee of that role **provisions** its
routines automatically — no operator ``add`` needed. Two halves:

* a **built-in** role: hiring a PM auto-creates its weekly planning routine;
* a **brand-new** role you define here: register it, hire into it, and its declared routine schedules
  too — with **zero change to the kernel**. That is the whole point: an organization's recurring work
  is data plugged into a fixed engine.

    uv run python consumer-facing-api/examples/09_plugin_routines.py
"""

from __future__ import annotations

from _common import offline_org

from chorus import RoutineDeclaration
from chorus.outcomes import Verifier
from chorus.roles import MemoryScope, RoleManifest, RolePlugin


def _routines(org: object, employee: str) -> list[str]:
    return [f"{r.intent_template[:48]!r} ({r.triggers[0].cron_expression})"
            for r in org.routines.list(employee=employee)]  # type: ignore[attr-defined]


def main() -> None:
    org = offline_org().chorus

    # 1) A built-in role that ships a routine: a hired PM auto-provisions its weekly planning review.
    org.hire(name="ada", role="pm")
    print("hired a PM — its routines appeared on hire:")
    for line in _routines(org, "ada"):
        print(f"  • {line}")

    # 2) A role the kernel never knew about — defined right here, outside src/chorus.
    nightly_audit = RoutineDeclaration(
        routine_key="widget-nightly-audit",
        intent_template="audit the widget inventory and open issues for anomalies",
        schedule="0 2 * * *",  # 02:00 daily
    )
    widget = RolePlugin(
        name="widget",
        manifest=RoleManifest(system_prompt="You build and audit widgets.",
                              tools=("read_file", "write_file"), memory_scope=MemoryScope.PROJECT),
        dod_generator=lambda intent: Verifier.command("pytest -q"),
        outcome_kind="pr",
        declared_routines=(nightly_audit,),
    )
    org.workforce.register_role(widget)  # the only step — no scheduler/ledger edit
    org.hire(name="wendy", role="widget")
    print("\nregistered a brand-new 'widget' role and hired one — its routine scheduled itself:")
    for line in _routines(org, "wendy"):
        print(f"  • {line}")

    print("\n(no diff under src/chorus — the reconciler never names a role)")


if __name__ == "__main__":
    main()
